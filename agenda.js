/* A lista e o formulário usam o catálogo e a disponibilidade do servidor. */
(() => {
  "use strict";
  const porId = id => document.getElementById(id);
  const parametros = new URLSearchParams(location.search);
  const marcacao = porId("marcacao");
  let catalogo;

  function elemento(tag, classe, texto) {
    const item = document.createElement(tag);
    if (classe) item.className = classe;
    if (texto !== undefined) item.textContent = texto;
    return item;
  }

  function avisar(texto = "") {
    porId("aviso").textContent = texto;
    porId("aviso").hidden = !texto;
  }

  function erroVisivel(erro) {
    if (erro.status === 401) {
      entrar();
      return;
    }
    avisar(erro.message || "Falha ao consultar a agenda. Tente novamente.");
  }

  function entrar() {
    const retorno = location.pathname.split("/").pop() + location.search;
    location.replace("login.html?voltar=" + encodeURIComponent(retorno));
  }

  function procurarServico(id) {
    return catalogo.servicos.find(item => item.id === id);
  }

  function procurarProfissional(id) {
    return catalogo.profissionais.find(item => item.id === id);
  }

  function criarTabela(linhas, corpo) {
    corpo.replaceChildren();
    for (const [rotulo, valor] of linhas) {
      const linha = elemento("tr");
      const cabecalho = elemento("th", "", rotulo);
      cabecalho.scope = "row";
      linha.append(cabecalho, elemento("td", "", valor));
      corpo.append(linha);
    }
  }

  function dadosAtendimento(reserva) {
    const servico = procurarServico(reserva.servico);
    return [
      ["Serviço", servico.nome],
      ["Profissional", procurarProfissional(reserva.profissional).nome],
      ["Data", dataBR(reserva.data)],
      ["Horário", reserva.horario],
      ["Duração", servico.duracao + " min"],
      ["Valor", moeda(servico.preco)]
    ];
  }

  function escolhas(container, itens, selecionado, aoEscolher, classe = "opcao") {
    container.replaceChildren();
    for (const item of itens) {
      const botao = elemento("button", classe, item.nome);
      botao.type = "button";
      if (item.descricao) botao.append(elemento("small", "", item.descricao));
      function marcar(ativo) {
        botao.classList.toggle(classe === "horario" ? "selecionado" : "selecionada", ativo);
        botao.setAttribute("aria-pressed", String(ativo));
      }
      marcar(item.id === selecionado);
      botao.addEventListener("click", () => {
        const anterior = container.querySelector('[aria-pressed="true"]');
        if (anterior) {
          anterior.classList.remove("selecionada", "selecionado");
          anterior.setAttribute("aria-pressed", "false");
        }
        marcar(true);
        aoEscolher(item.id);
      });
      container.append(botao);
    }
  }

  async function montarMarcacao() {
    const idEdicao = parametros.get("reagendar");
    let anterior = null;
    if (idEdicao !== null) {
      const resposta = await api("/api/agendamentos");
      anterior = resposta.agendamentos.find(item => String(item.id) === idEdicao && item.status === "confirmado");
      if (!anterior) {
        avisar("Este agendamento está indisponível para alteração. Consulte Meus agendamentos.");
        porId("aviso").after(Object.assign(elemento("a", "btn secundario", "Ver meus agendamentos"), {href: "agendamentos.html"}));
        return;
      }
      porId("titulo").textContent = "Reagendar horário";
      document.title = "Reagendar horário — Emi Belezaria";
      porId("introducao").textContent = procurarServico(anterior.servico).nome + " com " + procurarProfissional(anterior.profissional).nome
        + ". Horário atual: " + dataBR(anterior.data) + " às " + anterior.horario + ".";
      porId("confirmar").textContent = "Confirmar reagendamento";
      porId("voltarData").hidden = true;
      porId("sairReagendamento").hidden = false;
    }
    const consultaInicial = procurarServico(parametros.get("servico"));
    const reserva = anterior ? {...anterior} : {
      servico: consultaInicial?.id || "", profissional: "", data: "", horario: ""
    };
    const campoData = porId("data");
    campoData.min = catalogo.hoje;
    campoData.max = catalogo.limite;
    campoData.value = reserva.data;
    porId("periodo").textContent = "De segunda a sábado, entre " + dataBR(catalogo.hoje) + " e " + dataBR(catalogo.limite) + ".";
    campoData.addEventListener("input", () => campoData.setCustomValidity(""));
    let etapa;
    let busca = 0;

    function mostrar(numero, moverFoco = true) {
      etapa = numero;
      busca += 1;
      avisar();
      document.querySelectorAll(".passo").forEach((passo, i) => {
        passo.hidden = i + 1 !== numero;
        passo.classList.toggle("ativo", i + 1 === numero);
      });
      document.querySelectorAll(".etapa-bolha").forEach((bolha, i) => {
        bolha.classList.toggle("atual", i + 1 === numero);
        bolha.classList.toggle("feita", i + 1 < numero);
        if (i + 1 === numero) bolha.setAttribute("aria-current", "step");
        else bolha.removeAttribute("aria-current");
      });
      if (moverFoco) porId("passo" + numero).querySelector("h2").focus();
    }

    function escolherProfissional() {
      const permitida = procurarServico(reserva.servico).profissional;
      const profissionais = catalogo.profissionais.filter(item => item.id === permitida)
        .map(item => ({...item, descricao: item.especialidade}));
      escolhas(porId("profissionais"), profissionais, reserva.profissional, id => {
        reserva.profissional = id;
        porId("avancar2").disabled = false;
      });
      porId("avancar2").disabled = !reserva.profissional;
      mostrar(2);
    }

    async function consultarHorarios(mensagem = "") {
      mostrar(4);
      const consulta = busca;
      reserva.horario = "";
      porId("avancar4").disabled = true;
      porId("horarios").replaceChildren();
      porId("diaHorario").textContent = dataBR(reserva.data) + " · " + procurarProfissional(reserva.profissional).nome;
      avisar("Consultando horários disponíveis…");
      const filtros = new URLSearchParams({servico: reserva.servico, profissional: reserva.profissional, data: reserva.data});
      if (anterior) filtros.set("ignorar", anterior.id);
      try {
        const resposta = await api("/api/horarios?" + filtros);
        if (consulta !== busca) return;
        const horarios = resposta.horarios.filter(hora => !anterior || anterior.data !== reserva.data || anterior.horario !== hora);
        const itens = horarios.map(hora => ({id: hora, nome: hora}));
        escolhas(porId("horarios"), itens, reserva.horario, hora => {
          reserva.horario = hora;
          porId("avancar4").disabled = false;
          avisar();
        }, "horario");
        const disponiveis = horarios.length ? "" : "Nenhum horário disponível. Escolha outra data.";
        avisar([mensagem, disponiveis].filter(Boolean).join(" "));
      } catch (erro) {
        if (consulta === busca) {
          erroVisivel(erro);
          const tentar = elemento("button", "btn secundario", "Consultar novamente");
          tentar.addEventListener("click", () => consultarHorarios());
          porId("horarios").append(tentar);
        }
      }
    }

    escolhas(porId("servicos"), catalogo.servicos.map(s => ({...s, descricao: s.duracao + " min · " + moeda(s.preco)})),
      reserva.servico, id => {
        if (reserva.servico !== id) {
          reserva.profissional = "";
          reserva.horario = "";
        }
        reserva.servico = id;
        porId("avancar1").disabled = false;
      });
    porId("avancar1").disabled = !reserva.servico;
    porId("avancar1").addEventListener("click", escolherProfissional);
    porId("avancar2").addEventListener("click", () => mostrar(3));
    porId("avancar3").addEventListener("click", () => {
      campoData.setCustomValidity("");
      if (campoData.value && new Date(campoData.value + "T12:00:00").getDay() === 0) {
        campoData.setCustomValidity("O salão atende de segunda a sábado. Escolha outra data.");
      }
      if (!campoData.reportValidity()) return;
      reserva.data = campoData.value;
      consultarHorarios();
    });
    porId("avancar4").addEventListener("click", () => {
      criarTabela(dadosAtendimento(reserva), porId("resumo"));
      mostrar(5);
    });
    document.querySelectorAll("[data-voltar]").forEach(botao => {
      botao.addEventListener("click", () => {
        const numero = Number(botao.dataset.voltar);
        if (numero === 4) consultarHorarios();
        else mostrar(numero);
      });
    });
    const confirmar = porId("confirmar");
    confirmar.addEventListener("click", async () => {
      if (etapa !== 5 || confirmar.disabled) return;
      confirmar.disabled = true;
      porId("voltarResumo").disabled = true;
      avisar("Salvando agendamento…");
      const destino = anterior ? "/api/agendamentos/" + anterior.id + "/reagendar" : "/api/agendamentos";
      const body = anterior ? {data: reserva.data, horario: reserva.horario} : reserva;
      try {
        const {agendamento} = await api(destino, {method: "POST", body});
        porId("fluxo").hidden = true;
        porId("sucesso").hidden = false;
        porId("conclusao").textContent = anterior ? "Reagendamento confirmado" : "Agendamento confirmado";
        porId("comprovante").textContent = procurarServico(agendamento.servico).nome + " com " + procurarProfissional(agendamento.profissional).nome
          + " em " + dataBR(agendamento.data) + " às " + agendamento.horario + ".";
        avisar();
        porId("conclusao").focus();
      } catch (erro) {
        if (erro.status === 409) await consultarHorarios(erro.message);
        else erroVisivel(erro);
      } finally {
        confirmar.disabled = false;
        porId("voltarResumo").disabled = false;
      }
    });
    porId("fluxo").hidden = false;
    mostrar(anterior ? 3 : 1, false);
  }

  function cartao(reserva, aoCancelar) {
    const card = elemento("article", "card");
    const titulo = elemento("h3", "", procurarServico(reserva.servico).nome);
    const rotulo = {confirmado: "Confirmado", cancelado: "Cancelado", encerrado: "Horário encerrado", em_atendimento: "No horário do atendimento"};
    const status = elemento("span", "badge " + reserva.status, rotulo[reserva.status]);
    const topo = elemento("div", "agendamento-item");
    topo.append(titulo, status);
    const horario = elemento("p", "", dataBR(reserva.data) + " às " + reserva.horario + " · " + procurarProfissional(reserva.profissional).nome);
    const detalhes = elemento("details", "detalhes-reserva resumo");
    const tabela = elemento("table");
    const corpo = elemento("tbody");
    criarTabela(dadosAtendimento(reserva), corpo);
    tabela.append(corpo);
    detalhes.append(elemento("summary", "", "Ver detalhes"), tabela);
    card.append(topo, horario, detalhes);
    if (reserva.status !== "confirmado") return card;
    const acoes = elemento("div", "acoes");
    const reagendar = elemento("a", "btn secundario", "Reagendar");
    reagendar.href = "agendar.html?reagendar=" + encodeURIComponent(reserva.id);
    const cancelar = elemento("button", "btn texto", "Cancelar");
    acoes.append(reagendar, cancelar);
    const pergunta = elemento("div", "confirmar-cancelamento");
    pergunta.hidden = true;
    const manter = elemento("button", "btn secundario", "Manter agendamento");
    const confirmar = elemento("button", "btn", "Confirmar cancelamento");
    const opcoes = elemento("div", "acoes");
    opcoes.append(manter, confirmar);
    pergunta.append(elemento("p", "", "Cancelar este agendamento de " + dataBR(reserva.data) + " às " + reserva.horario + "?"), opcoes);
    cancelar.addEventListener("click", () => {
      pergunta.hidden = false;
      acoes.hidden = true;
      manter.focus();
    });
    manter.addEventListener("click", () => {
      pergunta.hidden = true;
      acoes.hidden = false;
      cancelar.focus();
    });
    confirmar.addEventListener("click", async () => {
      confirmar.disabled = manter.disabled = true;
      try {
        const resposta = await api("/api/agendamentos/" + reserva.id + "/cancelar", {method: "POST", body: {}});
        aoCancelar(resposta.agendamento);
      } catch (erro) {
        erroVisivel(erro);
      } finally {
        confirmar.disabled = manter.disabled = false;
      }
    });
    card.append(acoes, pergunta);
    return card;
  }

  async function montarAgenda() {
    const {agendamentos} = await api("/api/agendamentos");
    function ordenar(a, b) {
      return (a.data + a.horario).localeCompare(b.data + b.horario);
    }
    function preencher(id, itens, vazio) {
      const lista = porId(id);
      lista.replaceChildren();
      if (!itens.length) lista.append(elemento("p", "card", vazio));
      for (const reserva of itens) {
        lista.append(cartao(reserva, atualizada => {
          Object.assign(reserva, atualizada);
          renderizar();
          avisar("Agendamento cancelado. Você pode consultá-lo no histórico.");
          porId("aviso").tabIndex = -1;
          porId("aviso").focus();
        }));
      }
    }
    function renderizar() {
      const atuais = agendamentos.filter(r => r.status === "confirmado" || r.status === "em_atendimento");
      const historico = agendamentos.filter(r => r.status === "cancelado" || r.status === "encerrado");
      preencher("proximos", atuais.sort(ordenar), "Você ainda não tem horários marcados.");
      preencher("historico", historico.sort((a, b) => ordenar(b, a)), "Você ainda não tem horários no histórico.");
    }
    renderizar();
    avisar();
    porId("listas").hidden = false;
  }

  async function iniciar() {
    try {
      if (!await window.sessaoPronta) {
        entrar();
        return;
      }
      catalogo = await api("/api/catalogo");
      if (marcacao) await montarMarcacao();
      else await montarAgenda();
    } catch (erro) {
      erroVisivel(erro);
      porId("tentar").hidden = false;
      porId("tentar").addEventListener("click", () => location.reload());
    }
  }
  window.addEventListener("pageshow", evento => {
    if (evento.persisted) location.reload();
  });
  iniciar();
})();
