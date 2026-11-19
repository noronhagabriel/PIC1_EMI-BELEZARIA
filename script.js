"use strict";

async function api(path, options = {}) {
  const config = { ...options, credentials: "same-origin", cache: "no-store" };
  if (options.body !== undefined) {
    config.headers = { ...options.headers, "Content-Type": "application/json" };
    config.body = JSON.stringify(options.body);
  }
  let response;
  let data;
  try {
    response = await fetch(path, config);
    data = await response.json();
  } catch {
    throw new Error("Não foi possível acessar o salão. Verifique se o servidor está em execução e tente novamente.");
  }
  if (!response.ok) {
    const erro = new Error(data.erro || "Não foi possível concluir a solicitação.");
    erro.status = response.status;
    throw erro;
  }
  return data;
}

const moeda = valor => new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(valor);
const dataBR = iso => iso.split("-").reverse().join("/");
const descricoes = {
  corte: "Corte personalizado de acordo com seu estilo.",
  escova: "Finalização e modelagem dos cabelos.",
  manicure: "Cuidados e esmaltação das unhas das mãos.",
  pedicure: "Cuidados e esmaltação das unhas dos pés.",
  hidratacao: "Tratamento para hidratação e recuperação dos fios.",
  coloracao: "Coloração completa dos cabelos.",
  sobrancelhas: "Modelagem e acabamento das sobrancelhas."
};

function criarElemento(tag, texto, classe) {
  const el = document.createElement(tag);
  if (texto !== undefined) el.textContent = texto;
  if (classe) el.className = classe;
  return el;
}

function linkPara(texto, href, classe) {
  const el = criarElemento("a", texto, classe);
  el.href = href;
  return el;
}

function localDeRetorno() {
  const valor = new URLSearchParams(location.search).get("voltar");
  if (valor && URL.canParse(valor, location.href)) {
    const destino = new URL(valor, location.href);
    if (destino.origin === location.origin &&
        ["/agendar.html", "/agendamentos.html", "/servicos.html", "/index.html"].includes(destino.pathname)) {
      return destino.pathname + destino.search;
    }
  }
  return "index.html";
}

function mostrarAcesso(usuario) {
  const area = document.querySelector(".cliente-logada");
  if (!area) return;
  area.replaceChildren();
  if (!usuario) {
    if (document.body.dataset.pagina !== "login") {
      area.append(linkPara("Entrar", "login.html?voltar=" + encodeURIComponent(location.pathname + location.search), "acesso"));
    }
    return;
  }
  const nome = usuario.nome.trim().split(/\s+/)[0];
  const sair = criarElemento("button", "Sair", "acesso");
  sair.type = "button";
  sair.addEventListener("click", async () => {
    sair.disabled = true;
    try {
      await api("/api/logout", { method: "POST", body: {} });
      location.replace("index.html");
    } catch (erro) {
      area.append(criarElemento("span", erro.message));
      sair.disabled = false;
    }
  });
  area.append(criarElemento("span", "Olá, " + nome, "saudacao"), sair);
}

window.sessaoPronta = api("/api/sessao").then(({ usuario }) => {
  mostrarAcesso(usuario);
  return usuario;
});
window.sessaoPronta.catch(erro => {
  const area = document.querySelector(".cliente-logada");
  if (area) area.textContent = "Sessão indisponível";
});

const menu = document.querySelector(".menu-toggle");
menu?.addEventListener("click", () => {
  const aberto = document.getElementById("menuPrincipal").classList.toggle("aberto");
  menu.setAttribute("aria-expanded", String(aberto));
});

function criarCartao(servico, profissional) {
  const cartao = criarElemento("article", undefined, "servico-card");
  const titulo = criarElemento("h3", servico.nome);
  const info = criarElemento("div", undefined, "info");
  info.append(criarElemento("span", servico.duracao + " min"), criarElemento("span", moeda(servico.preco), "preco"));
  const link = linkPara("Agendar", "agendar.html?servico=" + encodeURIComponent(servico.id), "link");
  link.setAttribute("aria-label", "Agendar " + servico.nome);
  cartao.append(criarElemento("p", profissional.nome, "profissional"), titulo,
    criarElemento("p", descricoes[servico.id], "desc"), info, link);
  return cartao;
}

async function carregarCatalogo() {
  const area = document.getElementById("catalogo");
  const inicio = document.body.dataset.pagina === "index";
  const { servicos, profissionais } = await api("/api/catalogo");
  const destaque = ["corte", "escova", "manicure", "sobrancelhas"];
  for (const servico of servicos.filter(s => !inicio || destaque.includes(s.id))) {
    const profissional = profissionais.find(p => p.id === servico.profissional);
    area.append(criarCartao(servico, profissional));
  }
  if (!inicio || !(await window.sessaoPronta)) return;
  const proximo = document.getElementById("proximo");
  document.getElementById("proxima-secao").hidden = false;
  try {
    const { agendamentos } = await api("/api/agendamentos");
    const primeiro = agendamentos.filter(a => a.status === "confirmado")
      .sort((a, b) => (a.data + a.horario).localeCompare(b.data + b.horario))[0];
    if (!primeiro) {
      proximo.textContent = "Você ainda não tem horários marcados.";
      return;
    }
    const servico = servicos.find(s => s.id === primeiro.servico);
    const profissional = profissionais.find(p => p.id === primeiro.profissional);
    proximo.append(criarElemento("strong", servico.nome),
      criarElemento("p", dataBR(primeiro.data) + " às " + primeiro.horario + " com " + profissional.nome));
  } catch (erro) {
    proximo.textContent = erro.message;
  }
}

if (document.getElementById("catalogo")) {
  carregarCatalogo().catch(erro => {
    document.getElementById("catalogo").append(criarElemento("p", erro.message, "aviso"));
  });
}

function prepararConta() {
  const form = document.getElementById("form-conta");
  const nome = form.elements.nome;
  const senha = form.elements.senha;
  const erroConta = document.getElementById("erro-conta");
  const alternar = document.getElementById("alternar-conta");
  const enviar = document.getElementById("enviar-conta");
  let cadastro = false;

  alternar.addEventListener("click", () => {
    cadastro = !cadastro;
    document.getElementById("campo-nome").hidden = !cadastro;
    nome.disabled = !cadastro;
    nome.required = cadastro;
    senha.value = "";
    senha.autocomplete = cadastro ? "new-password" : "current-password";
    senha.minLength = cadastro ? 8 : 1;
    document.getElementById("titulo-conta").textContent = cadastro ? "Criar sua conta" : "Entrar na sua conta";
    document.getElementById("orientacao").textContent = cadastro
      ? "Informe seu nome, e-mail e uma senha com pelo menos 8 caracteres."
      : "Acesse sua agenda com o e-mail cadastrado.";
    document.getElementById("pergunta-conta").textContent = cadastro ? "Já tem uma conta?" : "Primeira visita?";
    alternar.textContent = cadastro ? "Entrar" : "Criar uma conta";
    enviar.textContent = cadastro ? "Cadastrar e continuar" : "Entrar";
    erroConta.hidden = true;
    (cadastro ? nome : form.elements.email).focus();
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const body = { email: form.elements.email.value.trim(), senha: senha.value };
    if (cadastro) body.nome = nome.value.trim();
    enviar.disabled = true;
    alternar.disabled = true;
    erroConta.hidden = true;
    try {
      await api(cadastro ? "/api/cadastro" : "/api/login", { method: "POST", body });
      location.replace(localDeRetorno());
    } catch (erro) {
      erroConta.textContent = erro.message;
      erroConta.hidden = false;
    } finally {
      enviar.disabled = false;
      alternar.disabled = false;
    }
  });
  window.sessaoPronta.then(usuario => { if (usuario) location.replace(localDeRetorno()); }).catch(() => {});
}
if (document.getElementById("form-conta")) prepararConta();
