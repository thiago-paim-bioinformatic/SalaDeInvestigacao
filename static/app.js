/* app.js - interação do front-end com a API Flask (server.py) */

const api = {
  get: (rota) => fetch(rota).then((r) => r.json()),
  post: (rota, corpo) =>
    fetch(rota, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corpo),
    }).then(async (r) => {
      let dados;
      try {
        dados = await r.json();
      } catch (e) {
        dados = { erro: await r.text() };
      }
      return { ok: r.ok, status: r.status, dados };
    }),
};

const $ = (id) => document.getElementById(id);

let agentesCarregados = [];
let dadosAgentes = {};

let config = { nome: "", persona: "", habilidades: "", tarefa: "" };

let arquivosSelecionados = [];

/* ---------- orquestração (estado) ---------- */
let noContador = 0;
let nosOrq = [];
let arestasOrq = [];
let portaSelecionada = null;
let escalaOrq = 1;
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 2;
const ZOOM_PASSO = 0.25;

/* ---------- utilitários de preenchimento ---------- */

function preencherSelect(id, itens, vazio) {
  const select = $(id);
  select.innerHTML = "";
  if (!itens || itens.length === 0) {
    const op = document.createElement("option");
    op.value = "";
    op.textContent = vazio;
    op.disabled = true;
    op.selected = true;
    select.appendChild(op);
    return;
  }
  itens.forEach((item) => {
    const op = document.createElement("option");
    op.value = item;
    op.textContent = item;
    select.appendChild(op);
  });
}

function aparar(texto) {
  const reduzido = (texto || "").slice(0, 600);
  const marca = texto && texto.length > 600 ? "\n... (conteúdo truncado)" : "";
  return reduzido + marca;
}

function escHtml(texto) {
  return (texto == null ? "" : String(texto))
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function inlineMarkdown(texto) {
  return texto
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function renderizarMarkdown(texto) {
  const blocosCodigo = [];
  const corpo = (texto == null ? "" : String(texto)).replace(/```([\s\S]*?)```/g, (m, bloco) => {
    blocosCodigo.push(`<pre class="bloco-codigo">${escHtml(bloco).trim()}</pre>`);
    return `\u0000${blocosCodigo.length - 1}\u0000`;
  });
  const linhas = corpo.split("\n");
  const html = [];
  let emLista = false;
  for (const linhaBruta of linhas) {
    const linha = linhaBruta.trimEnd();
    if (!linha.trim()) continue;
    if (linha.trim() === "---") {
      emLista = false;
      html.push("<hr>");
      continue;
    }
    const nivelCabecalho = linha.match(/^#{1,3}\s/);
    const itemLista = linha.match(/^\s*[-*]\s+/);
    if (emLista && (!itemLista || nivelCabecalho)) {
      html.push("</ul>");
      emLista = false;
    }
    if (nivelCabecalho) {
      const nivel = nivelCabecalho[0].trim().length;
      html.push(`<h${nivel}>${inlineMarkdown(escHtml(linha.replace(/^#{1,3}\s*/, "")))}</h${nivel}>`);
    } else if (itemLista) {
      if (!emLista) {
        html.push("<ul>");
        emLista = true;
      }
      html.push(`<li>${inlineMarkdown(escHtml(linha.replace(/^\s*[-*]\s*/, "")))}</li>`);
    } else {
      html.push(`<p>${inlineMarkdown(escHtml(linha))}</p>`);
    }
  }
  if (emLista) html.push("</ul>");
  return html.join("\n").replace(/\u0000(\d+)\u0000/g, (m, i) => blocosCodigo[Number(i)]);
}

let ultimoTextoOrqCopiar = "";

async function copiarTextoGerado() {
  if (!ultimoTextoOrqCopiar) return;
  try {
    await navigator.clipboard.writeText(ultimoTextoOrqCopiar);
  } catch (e) {
    const area = document.createElement("textarea");
    area.value = ultimoTextoOrqCopiar;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

function formatarTrechos(trechos) {
  if (!trechos || trechos.length === 0) {
    return "Nenhum trecho utilizado como contexto.";
  }
  return trechos
    .map(
      (t, i) =>
        `---- Trecho ${i + 1} ----\n` +
        `Fonte: ${t.fonte}\n` +
        `Página: ${t.pagina}\n` +
        `Conteúdo:\n${t.conteudo}`
    )
    .join("\n\n");
}

/* ---------- abas principais ---------- */

function alternarAba(btn) {
  const alvo = btn.dataset.alvo;
  document.querySelectorAll("#abas-principais button").forEach((b) => {
    b.classList.toggle("aba-ativa", b === btn);
  });
  document.querySelectorAll(".painel").forEach((p) => {
    p.hidden = p.dataset.aba !== alvo;
  });
}

/* ---------- sub-abas (orquestração) ---------- */

function alternarSubaba(btn) {
  const sub = btn.dataset.sub;
  document.querySelectorAll(".sub-abas button").forEach((b) => {
    b.classList.toggle("sub-ativa", b === btn);
  });
  $("sub-ambiente").hidden = sub !== "sub-ambiente";
  $("sub-entradas-saidas").hidden = sub !== "sub-entradas-saidas";
}

/* ---------- diálogos (pop-ups) ---------- */

function abrirDialog(id) {
  $(id).showModal();
}

function fecharDialog(id) {
  $(id).close();
}

function atualizarResumoConfig() {
  const linhas = [
    `Nome: ${config.nome || "(não configurado)"}`,
    `Persona: ${config.persona || "(não configurada)"}`,
    `Habilidades: ${config.habilidades || "(não configuradas)"}`,
    `Tarefa: ${config.tarefa || "(não configurada)"}`,
    `Tipo de retriever: ${$("retriever-agente-config").value}`,
    `Base de conhecimento: ${$("selecao-conhecimento").value || "(nenhuma)"}`,
  ];
  $("config-agente-resumo").textContent = linhas.join("\n");
}

document.querySelectorAll("[data-confirmar]").forEach((bt) => {
  bt.addEventListener("click", () => {
    const id = bt.dataset.confirmar;
    if (id === "dialog-nome") {
      config.nome = $("campo-nome").value.trim();
    } else if (id === "dialog-persona") {
      config.persona = $("campo-persona").value.trim();
    } else if (id === "dialog-habilidades") {
      config.habilidades = $("campo-habilidades").value.trim();
    } else if (id === "dialog-tarefa") {
      config.tarefa = $("campo-tarefa").value.trim();
    }
    fecharDialog(id);
    atualizarResumoConfig();
  });
});

document.querySelectorAll("[data-fechar]").forEach((bt) => {
  bt.addEventListener("click", () => fecharDialog(bt.dataset.fechar));
});

/* ---------- cargas iniciais ---------- */

async function carregarStatus() {
  const s = await api.get("/api/status");
  const servidor = s.servidor;
  $("status-servidor").textContent = JSON.stringify(
    {
      modelo_embedding: s.modelo_embedding,
      modelo_llm: s.modelo_llm,
      base_url: s.base_url,
      api_key: s.api_key,
      servidor_lm_studio: servidor.ativo ? "online" : "offline (" + servidor.erro + ")",
      modelos_carregados: servidor.modelos || servidor.erro,
    },
    null,
    2
  );
}

async function carregarBases() {
  const bases = await api.get("/api/conhecimentos");
  preencherSelect("selecao-conhecimento", bases, "Nenhuma base criada");
  preencherSelecaoBaseExistente(bases);
  if (bases.length) {
    $("bases-lista").textContent = bases.map((b) => "- " + b).join("\n");
  }
  atualizarResumoConfig();
}

function preencherSelecaoBaseExistente(bases) {
  const select = $("selecao-base-existente");
  select.innerHTML = "";
  const opNova = document.createElement("option");
  opNova.value = "";
  opNova.textContent = "Criar nova base";
  select.appendChild(opNova);
  (bases || []).forEach((b) => {
    const op = document.createElement("option");
    op.value = b;
    op.textContent = b;
    select.appendChild(op);
  });
}

function travarBaseExistente() {
  const select = $("selecao-base-existente");
  const nomeBase = $("nome-base");
  if (select.value) {
    nomeBase.value = select.value;
    nomeBase.disabled = true;
  } else {
    nomeBase.disabled = false;
  }
}

function resetarSelecaoBaseExistente() {
  $("selecao-base-existente").value = "";
  $("nome-base").disabled = false;
}

async function carregarAgentes() {
  dadosAgentes = await api.get("/api/agentes");
  agentesCarregados = Object.keys(dadosAgentes);
  preencherSelect("selecao-agente", agentesCarregados, "Nenhum agente criado");
  preencherSelect("selecao-memoria", agentesCarregados, "Nenhum agente criado");
  montarPaleta();
  renderizarIconesAgentes();
}

function renderizarIconesAgentes() {
  const container = $("agentes-lista");
  container.innerHTML = "";
  if (agentesCarregados.length === 0) {
    container.textContent = "Nenhum agente criado ainda.";
    return;
  }
  agentesCarregados.forEach((nome) => {
    const icone = document.createElement("button");
    icone.type = "button";
    icone.className = "icone-agente";
    icone.textContent = nome;
    icone.title = "Clique para visualizar a estrutura JSON";
    icone.addEventListener("click", () => visualizarAgente(nome));
    container.appendChild(icone);
  });
}

function visualizarAgente(nome) {
  $("json-visualizar-agente").textContent = JSON.stringify(dadosAgentes[nome] || {}, null, 2);
  $("dialog-visualizar-agente").dataset.agente = nome;
  abrirDialog("dialog-visualizar-agente");
}

async function copiarJsonAgente() {
  const nome = $("dialog-visualizar-agente").dataset.agente;
  const dado = JSON.stringify(dadosAgentes[nome] || {}, null, 2);
  try {
    await navigator.clipboard.writeText(dado);
  } catch (e) {
    const area = document.createElement("textarea");
    area.value = dado;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

/* ---------- ações: base de conhecimento ---------- */

function atualizarInfoArquivos() {
  const info = $("info-arquivos-selecionados");
  if (arquivosSelecionados.length === 0) {
    info.textContent = "Nenhum arquivo/pasta selecionado.";
    return;
  }
  const rotulos = arquivosSelecionados
    .map((f) => f.webkitRelativePath || f.name)
    .slice(0, 5);
  const restante =
    arquivosSelecionados.length > 5
      ? " (e mais " + (arquivosSelecionados.length - 5) + " arquivo(s))"
      : "";
  info.textContent =
    arquivosSelecionados.length + " arquivo(s) selecionado(s): " + rotulos.join(", ") + restante;
}

async function criarBase() {
  const baseExistente = $("selecao-base-existente").value;
  const nome = baseExistente || $("nome-base").value.trim();
  if (!nome) {
    $("resultado-base").textContent = "Informe o nome da base de conhecimento.";
    return;
  }
  if (arquivosSelecionados.length === 0) {
    $("resultado-base").textContent =
      "Carregue arquivos individuais ou uma pasta pelo botão 'Carregar base de conhecimento'.";
    return;
  }
  const corpo = new FormData();
  corpo.append("nome", nome);
  corpo.append("genero", $("genero").value.trim() || "documento");
  corpo.append("especie", $("especie").value.trim() || "conhecimento");
  corpo.append("chunk_size", parseInt($("chunk-size").value, 10));
  corpo.append("chunk_overlap", parseInt($("chunk-overlap").value, 10));
  arquivosSelecionados.forEach((f) => corpo.append("files[]", f, f.webkitRelativePath || f.name));
  const bloco = $("bloco-progresso-base");
  const barra = $("progresso-base");
  const textoProgresso = $("texto-progresso-base");
  $("resultado-base").textContent = "";
  $("btn-base").disabled = true;

  let resp;
  try {
    resp = await fetch("/api/conhecimentos", {
      method: "POST",
      body: corpo,
    });
  } catch (e) {
    bloco.hidden = true;
    $("btn-base").disabled = false;
    resetarSelecaoBaseExistente();
    $("resultado-base").textContent = `ERRO: ${e}`;
    return;
  }

  const ehStream = (resp.headers.get("content-type") || "").includes("text/event-stream");
  if (!resp.ok || !ehStream) {
    bloco.hidden = true;
    $("btn-base").disabled = false;
    resetarSelecaoBaseExistente();
    let dados = { erro: await resp.text() };
    try {
      dados = await resp.json();
    } catch (ignorado) {}
    $("resultado-base").textContent = `ERRO (${resp.status}): ${dados.erro}`;
    return;
  }

  bloco.hidden = false;
  barra.value = 0;
  textoProgresso.textContent = "";

  const leitor = resp.body.getReader();
  const decodificador = new TextDecoder();
  let buffer = "";
  let tipoEvento = null;
  let resultadoFinal = null;
  let erroFinal = null;

  try {
    while (true) {
      const { done, value } = await leitor.read();
      if (done) break;
      buffer += decodificador.decode(value, { stream: true });
      const linhas = buffer.split("\n");
      buffer = linhas.pop();
      for (const linha of linhas) {
        const tratada = linha.trim();
        if (tratada.startsWith("event:")) {
          tipoEvento = tratada.slice(6).trim();
          continue;
        }
        if (!tratada.startsWith("data:")) continue;
        const conteudo = tratada.slice(5).trim();
        if (!conteudo) continue;
        let dados;
        try {
          dados = JSON.parse(conteudo);
        } catch (ignorado) {
          continue;
        }
        if (tipoEvento === "progresso" && dados.total) {
          barra.value = Math.round((dados.feitos / dados.total) * 100);
          textoProgresso.textContent = `${dados.feitos} de ${dados.total} lotes processados`;
        } else if (tipoEvento === "done") {
          resultadoFinal = dados;
        } else if (tipoEvento === "erro") {
          erroFinal = dados.erro;
        }
      }
    }
  } catch (e) {
    erroFinal = erroFinal || `Conexão interrompida: ${e}`;
  }

  bloco.hidden = true;
  $("btn-base").disabled = false;
  if (erroFinal) {
    resetarSelecaoBaseExistente();
    $("resultado-base").textContent = `ERRO: ${erroFinal}`;
  } else if (resultadoFinal) {
    resetarSelecaoBaseExistente();
    const tema = resultadoFinal.adicionada
      ? "atualizada"
      : "criada";
    const trechos = resultadoFinal.adicionada
      ? "novos trechos"
      : "trechos";
    $("resultado-base").textContent =
      `Base '${resultadoFinal.nome}' ${tema} com ${resultadoFinal.n_chunks} ${trechos} de ${resultadoFinal.n_arquivos} arquivo(s).`;
    await carregarBases();
  } else {
    resetarSelecaoBaseExistente();
    $("resultado-base").textContent = "ERRO: stream encerrado sem resultado. Tente novamente.";
  }
}

/* ---------- ações: agentes ---------- */

async function criarAgente() {
  const nome = config.nome.trim();
  const conhecimento = $("selecao-conhecimento").value;
  const retriever_type = $("retriever-agente-config").value;
  if (!nome) {
    $("resultado-agente").textContent =
      "Configure o Nome do Agente pelo botão 'Configurar Nome do Agente'.";
    return;
  }
  if (retriever_type !== "sem_base" && !conhecimento) {
    $("resultado-agente").textContent =
      "Selecione uma base de conhecimento (exceto em 'Não buscar na base de conhecimento').";
    return;
  }
  const corpo = {
    nome,
    persona: config.persona,
    habilidades: config.habilidades,
    tarefa: config.tarefa,
    conhecimento,
    retriever_type,
  };
  $("resultado-agente").textContent = "Criando agente...";
  const r = await api.post("/api/agentes", corpo);
  if (r.ok) {
    $("resultado-agente").textContent = `Agente '${r.dados.nome}' criado com sucesso.`;
    config = { nome: "", persona: "", habilidades: "", tarefa: "" };
    atualizarResumoConfig();
    await carregarAgentes();
  } else {
    $("resultado-agente").textContent = `ERRO (${r.status}): ${r.dados.erro}`;
  }
}

let agenteParaDeletar = null;

async function abrirListaDelecao() {
  await carregarAgentes();
  const lista = $("lista-deletar-agentes");
  lista.innerHTML = "";
  if (agentesCarregados.length === 0) {
    lista.textContent = "Nenhum agente criado.";
  } else {
    agentesCarregados.forEach((nome) => {
      const bt = document.createElement("button");
      bt.type = "button";
      bt.textContent = nome;
      bt.addEventListener("click", () => confirmarDelecao(nome));
      lista.appendChild(bt);
    });
  }
  abrirDialog("dialog-listar-deletar");
}

function confirmarDelecao(nome) {
  agenteParaDeletar = nome;
  $("texto-confirmar-deletar").textContent = `Confirma a exclusão do agente ${nome}?`;
  fecharDialog("dialog-listar-deletar");
  abrirDialog("dialog-confirmar-deletar");
}

async function excluirAgenteConfirmado() {
  const nome = agenteParaDeletar;
  agenteParaDeletar = null;
  fecharDialog("dialog-confirmar-deletar");
  if (!nome) return;
  $("resultado-agente").textContent = `Excluindo agente '${nome}'...`;
  const r = await api.post(`/api/agentes/${encodeURIComponent(nome)}/excluir`, {});
  if (r.ok) {
    const notaMemoria = r.dados.memoria_removida
      ? " e sua memória foi removida"
      : " (memória persistente não encontrada)";
    $("resultado-agente").textContent = `Agente '${nome}' excluído${notaMemoria}.`;
    await carregarAgentes();
  } else {
    $("resultado-agente").textContent = `ERRO (${r.status}): ${r.dados.erro}`;
  }
}

/* ---------- ações: interação individual ---------- */

async function perguntar() {
  const agente = $("selecao-agente").value;
  const pergunta = $("pergunta-agente").value.trim();
  if (!agente) {
    $("resultado-pergunta").textContent = "Crie e selecione um agente.";
    return;
  }
  if (!pergunta) {
    $("resultado-pergunta").textContent = "Digite uma pergunta.";
    return;
  }
  const corpo = {
    pergunta,
    retriever_type: $("retriever-agente").value,
    usar_memoria: $("usar-memoria").checked,
    salvar_memoria: $("salvar-memoria").checked,
    regex_pattern: $("regex-agente").value.trim() || null,
  };
  fecharDialog("dialog-pergunta");
  $("resultado-pergunta").textContent = "Executando agente...";
  $("btn-perguntar").disabled = true;
  const r = await api.post(`/api/agentes/${encodeURIComponent(agente)}/perguntar`, corpo);
  $("btn-perguntar").disabled = false;
  if (!r.ok) {
    $("resultado-pergunta").textContent = `ERRO (${r.status}): ${r.dados.erro}`;
    return;
  }
  const d = r.dados;
  const partes = [
    `=== AGENTE: ${d.agente} ===\n`,
    `PERGUNTA:\n${d.pergunta}\n`,
    `RESPOSTA:\n${d.resposta}\n`,
    `MEMÓRIA UTILIZADA:\n${aparar(d.memoria_utilizada)}\n`,
    `TRECHOS DO CONTEXTO:\n${formatarTrechos(d.trechos)}`,
  ];
  $("resultado-pergunta").textContent = partes.join("\n");
}

/* ---------- ações: memória ---------- */

async function acessarMemoria() {
  const pergunta = $("pergunta-memoria").value.trim();
  const agente = $("selecao-memoria").value;
  if (!agente) {
    $("resultado-memoria").textContent = "Crie e selecione um agente.";
    return;
  }
  if (!pergunta) {
    $("resultado-memoria").textContent = "Digite uma pergunta para a memória.";
    return;
  }
  $("resultado-memoria").textContent = "Consultando memória...";
  const r = await api.post(`/api/agentes/${encodeURIComponent(agente)}/memoria/acessar`, {
    pergunta,
    retriever_type: "mmr",
  });
  if (!r.ok) {
    $("resultado-memoria").textContent = `ERRO (${r.status}): ${r.dados.erro}`;
    return;
  }
  const d = r.dados;
  $("resultado-memoria").textContent =
    `=== MEMÓRIA DO AGENTE: ${agente} ===\n\n` +
    `RESPOSTA COM BASE NA MEMÓRIA:\n${d.resposta_memoria}\n\n` +
    `TRECHOS DA MEMÓRIA:\n${formatarTrechos(d.trechos_memoria)}`;
}

/* ---------- orquestração: paleta e ambiente ---------- */

function montarPaleta() {
  const paleta = $("paleta-itens");
  paleta.innerHTML = "";

  const addItem = (tipo, rotulo, agente) => {
    const div = document.createElement("div");
    div.className = "item-paleta " + tipo;
    div.draggable = true;
    div.innerHTML = `<span class="icone-cor"></span><span>${rotulo}</span>`;
    if (tipo === "usuario") {
      const bt = document.createElement("button");
      bt.type = "button";
      bt.className = "btn-paleta";
      bt.textContent = "Interação inicial";
      bt.addEventListener("click", () => abrirDialog("dialog-interacao"));
      div.appendChild(bt);
    }
    div.addEventListener("dragstart", (ev) => {
      ev.dataTransfer.setData("text/plain", JSON.stringify({ tipo, agente: agente || "" }));
      ev.dataTransfer.effectAllowed = "copy";
    });
    paleta.appendChild(div);
  };

  addItem("usuario", "Usuário", "");
  addItem("saida", "Saída", "");
  if (agentesCarregados.length === 0) {
    const span = document.createElement("span");
    span.className = "dica-area";
    span.textContent = "Nenhum agente criado ainda.";
    paleta.appendChild(span);
  }
  agentesCarregados.forEach((nome) => addItem("agente", nome, nome));
}

function criarNoDOM(item) {
  const area = $("canvas-orquestracao");
  const div = document.createElement("div");
  div.className = "no-orq " + item.tipo;
  div.dataset.noId = item.id;
  const rotulo =
    item.tipo === "usuario" ? "Usuário" : item.tipo === "saida" ? "Saída" : "Agente";
  const nome = item.tipo === "agente" ? item.agente : rotulo;
  div.innerHTML = `
    <span class="rotulo">${rotulo}</span>
    <div class="nome-no">${nome}</div>
    <button type="button" class="porta input" data-no-id="${item.id}" data-porta="input" title="input"></button>
    <button type="button" class="porta output" data-no-id="${item.id}" data-porta="output" title="output"></button>`;
  if (item.tipo === "usuario") {
    const bt = document.createElement("button");
    bt.type = "button";
    bt.className = "btn-paleta";
    bt.textContent = "Interação inicial";
    bt.style.marginTop = "10px";
    bt.style.display = "block";
    bt.addEventListener("click", () => abrirDialog("dialog-interacao"));
    div.appendChild(bt);
  }
  div.style.left = item.x + "px";
  div.style.top = item.y + "px";
  div.addEventListener("mousedown", iniciarArrastarNo);
  div.querySelectorAll(".porta").forEach((p) => p.addEventListener("click", clicarPorta));
  area.appendChild(div);
}

function esconderDicaArea() {
  const dica = document.querySelector("#area-orquestracao .dica-area");
  if (dica) dica.style.display = "none";
}

function iniciarArrastarNo(ev) {
  if (ev.target.closest(".porta") || ev.target.closest("button")) return;
  const no = ev.target.closest(".no-orq");
  if (!no) return;
  const item = nosOrq.find((n) => n.id === no.dataset.noId);
  if (!item) return;
  const area = $("area-orquestracao");
  const rectArea = area.getBoundingClientRect();
  const inicialX = ev.clientX;
  const inicialY = ev.clientY;
  const orgX = item.x;
  const orgY = item.y;
  const limiteX = Math.max(0, rectArea.width / escalaOrq - 170);
  const limiteY = Math.max(0, rectArea.height / escalaOrq - 80);
  ev.preventDefault();

  function mover(ev2) {
    item.x = Math.max(0, Math.min(orgX + (ev2.clientX - inicialX) / escalaOrq, limiteX));
    item.y = Math.max(0, Math.min(orgY + (ev2.clientY - inicialY) / escalaOrq, limiteY));
    no.style.left = item.x + "px";
    no.style.top = item.y + "px";
    desenharArestas();
  }

  function soltar() {
    window.removeEventListener("mousemove", mover);
    window.removeEventListener("mouseup", soltar);
  }

  window.addEventListener("mousemove", mover);
  window.addEventListener("mouseup", soltar);
}

function limparSelecaoPorta() {
  if (portaSelecionada) {
    const no = document.querySelector(`.no-orq[data-no-id="${portaSelecionada.noId}"]`);
    if (no) {
      const porta = no.querySelector(`.porta.output`);
      if (porta) porta.classList.remove("selecionada");
    }
    portaSelecionada = null;
  }
}

function clicarPorta(ev) {
  ev.preventDefault();
  ev.stopPropagation();
  const porta = ev.currentTarget;
  const noId = porta.dataset.noId;
  const tipoPorta = porta.dataset.porta;

  if (!portaSelecionada) {
    if (tipoPorta !== "output") return; // conexão começa sempre em uma saída
    portaSelecionada = { noId, tipo: "output" };
    porta.classList.add("selecionada");
    return;
  }

  const origem = portaSelecionada;
  const valido = tipoPorta === "input" && origem.noId !== noId;
  if (valido) {
    const jaExiste = arestasOrq.some((a) => a.de === origem.noId && a.para === noId);
    if (!jaExiste) {
      arestasOrq.push({ de: origem.noId, para: noId });
      desenharArestas();
    }
  }
  limparSelecaoPorta();
}

function desenharArestas() {
  const svg = $("cv-arestas");
  svg.innerHTML = "";
  const canvas = $("canvas-orquestracao");
  const rect = canvas.getBoundingClientRect();
  for (const a of arestasOrq) {
    const elDe = document.querySelector(`.no-orq[data-no-id="${a.de}"]`);
    const elPara = document.querySelector(`.no-orq[data-no-id="${a.para}"]`);
    if (!elDe || !elPara) continue;
    const pDe = elDe.querySelector(".porta.output").getBoundingClientRect();
    const pPara = elPara.querySelector(".porta.input").getBoundingClientRect();
    const x1 = (pDe.left - rect.left + pDe.width / 2) / escalaOrq;
    const y1 = (pDe.top - rect.top + pDe.height / 2) / escalaOrq;
    const x2 = (pPara.left - rect.left + pPara.width / 2) / escalaOrq;
    const y2 = (pPara.top - rect.top + pPara.height / 2) / escalaOrq;
    const dx = Math.max(30, Math.abs(x2 - x1) / 2);
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute(
      "d",
      `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`
    );
    svg.appendChild(path);
  }
}

function aplicarZoom() {
  const canvas = $("canvas-orquestracao");
  canvas.style.transform = `scale(${escalaOrq})`;
  $("btn-zoom-reset").textContent = `${Math.round(escalaOrq * 100)}%`;
  desenharArestas();
}

function limparAmbiente() {
  nosOrq = [];
  arestasOrq = [];
  portaSelecionada = null;
  noContador = 0;
  const area = $("area-orquestracao");
  area.querySelectorAll(".no-orq").forEach((n) => n.remove());
  area.querySelector("#cv-arestas").innerHTML = "";
  const dica = area.querySelector(".dica-area");
  if (dica) dica.style.display = "";
  $("resultado-orquestracao").textContent = "Nenhuma orquestração executada ainda.";
  $("resultado-entradas-saidas").textContent =
    'Nenhuma execução ainda. Execute a orquestração na sub-aba "Ambiente de Orquestração".';
}

function tipoTxt(tipo) {
  return tipo === "usuario" ? "Usuário" : tipo === "saida" ? "Saída" : "Agente";
}

async function executarOrquestracao() {
  if (!nosOrq.length) {
    $("resultado-orquestracao").innerHTML = "<p>Arraste ao menos um elemento para o ambiente.</p>";
    return;
  }
  if (!nosOrq.some((n) => n.tipo === "usuario")) {
    $("resultado-orquestracao").innerHTML =
      "<p>Inclua o ícone Usuário e defina a interação inicial (botão 'Interação inicial').</p>";
    return;
  }
  const promptInicial = $("prompt-inicial-orq").value.trim();
  if (!promptInicial) {
    $("resultado-orquestracao").innerHTML =
      "<p>Defina a interação inicial no ícone Usuário (botão 'Interação inicial').</p>";
    return;
  }
  const corpo = {
    prompt_inicial: promptInicial,
    nos: nosOrq.map((n) => ({ id: n.id, tipo: n.tipo, agente: n.agente })),
    arestas: arestasOrq,
  };
  $("btn-executar-orq").disabled = true;
  $("resultado-orquestracao").innerHTML =
    "<p>Executando orquestração... pode levar alguns minutos. Acompanhe o 'Log do servidor'.</p>";
  $("resultado-entradas-saidas").innerHTML = "<p>Executando orquestração... pode levar alguns minutos.</p>";
  const r = await api.post("/api/orquestrador", corpo);
  $("btn-executar-orq").disabled = false;
  if (!r.ok) {
    $("resultado-orquestracao").innerHTML = `<p>ERRO (${r.status}): ${escHtml(r.dados.erro)}</p>`;
    return;
  }
  const d = r.dados;
  const blocosEntradas = d.sistema
    .map((item) => {
      const linhas = [
        `### ${item.id} (${tipoTxt(item.tipo)})`,
        `**Entrada:**\n\n${item.entrada || "(sem entrada)"}`,
        `**Saída:**\n\n${item.saida || "(sem saída)"}`,
      ];
      if (item.erro) linhas.push(`**Erro:**\n\n${item.erro}`);
      if (item.trechos && item.trechos.length) {
        linhas.push(`**Trechos do contexto:**\n\n${formatarTrechosMarkdown(item.trechos)}`);
      }
      return linhas.join("\n\n");
    })
    .join("\n\n---\n\n");
  const textoFinal = [
    `## Orquestração concluída`,
    `**Prompt inicial:**\n\n${d.prompt_inicial || "(vazio)"}`,
    d.saida ? `## Saída verificada no ícone "Saída"\n\n${d.saida}` : "(nenhuma saída definida)",
  ].join("\n\n");
  ultimoTextoOrqCopiar = textoFinal;
  $("resultado-orquestracao").innerHTML = renderizarMarkdown(textoFinal);
  $("resultado-entradas-saidas").innerHTML = renderizarMarkdown(blocosEntradas);
  const btSub = document.querySelector('#aba-orquestracao .sub-abas button[data-sub="sub-entradas-saidas"]');
  if (btSub) btSub.click();
}

function formatarTrechosMarkdown(trechos) {
  if (!trechos || trechos.length === 0) {
    return "Nenhum trecho utilizado como contexto.";
  }
  return trechos.map((t, i) =>
    `**Trecho ${i + 1}** — *Fonte:* ${t.fonte} — *Página:* ${t.pagina}\n\n${t.conteudo}`
  ).join("\n\n");
}

/* ---------- orquestração: gravar, listar e carregar ---------- */

async function gravarOrquestracao() {
  if (!nosOrq.length) {
    $("resultado-orquestracao").innerHTML = "<p>Arraste ao menos um elemento para o ambiente antes de gravar.</p>";
    return;
  }
  fecharDialog("dialog-gravar-orq");
  const nome = $("nome-orq-gravar").value.trim();
  if (!nome) {
    $("resultado-orquestracao").innerHTML = "<p>Informe um nome para a orquestração.</p>";
    return;
  }
  const corpo = {
    nome,
    nos: nosOrq.map((n) => ({ id: n.id, tipo: n.tipo, agente: n.agente, x: n.x, y: n.y })),
    arestas: arestasOrq,
    prompt_inicial: $("prompt-inicial-orq").value.trim(),
  };
  const r = await api.post("/api/orquestracoes", corpo);
  if (r.ok) {
    $("resultado-orquestracao").innerHTML = `<p>Orquestração <strong>${escHtml(nome)}</strong> gravada com sucesso.</p>`;
    $("nome-orq-gravar").value = "";
  } else {
    $("resultado-orquestracao").innerHTML = `<p>ERRO (${r.status}): ${escHtml(r.dados.erro)}</p>`;
  }
}

async function abrirListaOrqSalvas() {
  const lista = $("lista-orq-salvas");
  lista.innerHTML = "";
  const nomes = await api.get("/api/orquestracoes");
  if (!nomes.length) {
    lista.textContent = "Nenhuma orquestração salva.";
  } else {
    nomes.forEach((nome) => {
      const item = document.createElement("div");
      item.className = "lista-orq-item";
      const btCarregar = document.createElement("button");
      btCarregar.textContent = nome;
      btCarregar.title = "Carregar no ambiente";
      btCarregar.addEventListener("click", () => carregarOrquestracao(nome));
      const btExcluir = document.createElement("button");
      btExcluir.className = "btn-secundario";
      btExcluir.textContent = "Excluir";
      btExcluir.title = "Excluir orquestração salva";
      btExcluir.addEventListener("click", (ev) => {
        ev.stopPropagation();
        excluirOrquestracao(nome);
      });
      item.appendChild(btCarregar);
      item.appendChild(btExcluir);
      lista.appendChild(item);
    });
  }
  abrirDialog("dialog-orq-salvas");
}

async function carregarOrquestracao(nome) {
  const r = await api.post(`/api/orquestracoes/${encodeURIComponent(nome)}/carregar`, {});
  if (!r.ok) {
    $("resultado-orquestracao").innerHTML = `<p>ERRO: ${escHtml(r.dados.erro)}</p>`;
    return;
  }
  const d = r.dados;
  limparAmbiente();
  noContador = 0;
  (d.nos || []).forEach((n) => {
    const num = parseInt(String(n.id).replace(/\D/g, ""), 10) || 0;
    if (num > noContador) noContador = num;
  });
  (d.nos || []).forEach((n) => {
    const item = {
      id: n.id,
      tipo: n.tipo,
      agente: n.agente || "",
      x: Number.isFinite(n.x) ? n.x : 20,
      y: Number.isFinite(n.y) ? n.y : 20,
    };
    nosOrq.push(item);
    criarNoDOM(item);
  });
  arestasOrq = (d.arestas || []).map((a) => ({ de: String(a.de), para: String(a.para) }));
  $("prompt-inicial-orq").value = d.prompt_inicial || "";
  fecharDialog("dialog-orq-salvas");
  esconderDicaArea();
  desenharArestas();
  $("resultado-orquestracao").innerHTML = `<p>Orquestração <strong>${escHtml(nome)}</strong> carregada no ambiente.</p>`;
}

async function excluirOrquestracao(nome) {
  const r = await api.post(`/api/orquestracoes/${encodeURIComponent(nome)}/excluir`, {});
  if (r.ok) {
    await abrirListaOrqSalvas();
  }
}

/* ---------- Log do servidor em tempo real (SSE) ---------- */

function conectarLogServidor() {
  const painel = $("log-servidor");
  let primeira = true;
  const fonte = new EventSource("/api/logs");
  fonte.addEventListener("log", (ev) => {
    let entrada;
    try {
      entrada = JSON.parse(ev.data);
    } catch (ignorado) {
      return;
    }
    if (primeira) {
      painel.textContent = "";
      primeira = false;
    }
    const linha = document.createElement("div");
    linha.className = "log-entry " + (entrada.nivel === "erro" ? "erro" : "info");
    linha.textContent = `[${entrada.timestamp}] ${entrada.mensagem}`;
    painel.appendChild(linha);
    painel.scrollTop = painel.scrollHeight;
  });
  fonte.onerror = () => {};
}

/* ---------- inicialização ---------- */

document.addEventListener("DOMContentLoaded", () => {
  carregarStatus();
  carregarBases();
  carregarAgentes();

  document.querySelectorAll("#abas-principais button").forEach((btn) => {
    btn.addEventListener("click", () => alternarAba(btn));
  });
  document.querySelectorAll(".sub-abas button").forEach((btn) => {
    btn.addEventListener("click", () => alternarSubaba(btn));
  });

  $("btn-base").addEventListener("click", criarBase);
  $("selecao-base-existente").addEventListener("change", travarBaseExistente);
  $("btn-agente").addEventListener("click", criarAgente);
  $("btn-deletar-agente").addEventListener("click", abrirListaDelecao);
  $("btn-sim-deletar").addEventListener("click", excluirAgenteConfirmado);
  $("btn-copiar-agente").addEventListener("click", copiarJsonAgente);

  $("btn-selecionar-arquivos").addEventListener("click", () => abrirDialog("dialog-origem-arquivos"));
  $("btn-escolher-arquivos").addEventListener("click", () => {
    fecharDialog("dialog-origem-arquivos");
    $("arquivo-pdf-multiplo").click();
  });
  $("btn-escolher-pasta").addEventListener("click", () => {
    fecharDialog("dialog-origem-arquivos");
    $("arquivo-pdf-pasta").click();
  });
  $("arquivo-pdf-multiplo").addEventListener("change", (ev) => {
    arquivosSelecionados = Array.from(ev.target.files || []);
    atualizarInfoArquivos();
    ev.target.value = "";
  });
  $("arquivo-pdf-pasta").addEventListener("change", (ev) => {
    arquivosSelecionados = Array.from(ev.target.files || []);
    atualizarInfoArquivos();
    ev.target.value = "";
  });

  $("btn-config-nome").addEventListener("click", () => abrirDialog("dialog-nome"));
  $("btn-config-persona").addEventListener("click", () => abrirDialog("dialog-persona"));
  $("btn-config-habilidades").addEventListener("click", () => abrirDialog("dialog-habilidades"));
  $("btn-config-tarefa").addEventListener("click", () => abrirDialog("dialog-tarefa"));
  $("btn-pergunta-popup").addEventListener("click", () => abrirDialog("dialog-pergunta"));
  $("btn-regex-popup").addEventListener("click", () => abrirDialog("dialog-regex"));
  $("btn-perguntar").addEventListener("click", perguntar);

  $("retriever-agente-config").addEventListener("change", atualizarResumoConfig);
  $("selecao-conhecimento").addEventListener("change", atualizarResumoConfig);
  $("selecao-agente").addEventListener("change", () => {
    const dado = dadosAgentes[$("selecao-agente").value];
    if (dado && dado.retriever_type) {
      $("retriever-agente").value = dado.retriever_type;
    }
  });

  $("btn-memoria").addEventListener("click", acessarMemoria);

  /* orquestração */
  const area = $("area-orquestracao");
  ["dragover", "dragenter"].forEach((tipo) => {
    area.addEventListener(tipo, (e) => e.preventDefault());
  });
  area.addEventListener("drop", (e) => {
    e.preventDefault();
    let dados;
    try {
      dados = JSON.parse(e.dataTransfer.getData("text/plain") || "{}");
    } catch (ignorado) {
      return;
    }
    if (!dados.tipo || !["usuario", "saida", "agente"].includes(dados.tipo)) return;
    const rect = e.currentTarget.getBoundingClientRect();
    noContador += 1;
    const item = {
      id: "no" + noContador,
      tipo: dados.tipo,
      agente: dados.agente || "",
      x: Math.max(0, Math.min((e.clientX - rect.left) / escalaOrq - 75, rect.width / escalaOrq - 170)),
      y: Math.max(0, Math.min((e.clientY - rect.top) / escalaOrq - 20, rect.height / escalaOrq - 80)),
    };
    nosOrq.push(item);
    criarNoDOM(item);
    esconderDicaArea();
  });

  $("btn-executar-orq").addEventListener("click", executarOrquestracao);
  $("btn-limpar-orq").addEventListener("click", limparAmbiente);
  $("btn-copiar-orq").addEventListener("click", copiarTextoGerado);
  $("btn-gravar-orq").addEventListener("click", () => abrirDialog("dialog-gravar-orq"));
  $("btn-confirmar-gravar-orq").addEventListener("click", gravarOrquestracao);
  $("btn-orq-salvas").addEventListener("click", abrirListaOrqSalvas);
  $("btn-zoom-menor").addEventListener("click", () => {
    escalaOrq = Math.max(ZOOM_MIN, escalaOrq - ZOOM_PASSO);
    aplicarZoom();
  });
  $("btn-zoom-maior").addEventListener("click", () => {
    escalaOrq = Math.min(ZOOM_MAX, escalaOrq + ZOOM_PASSO);
    aplicarZoom();
  });
  $("btn-zoom-reset").addEventListener("click", () => {
    escalaOrq = 1;
    aplicarZoom();
  });

  conectarLogServidor();
});