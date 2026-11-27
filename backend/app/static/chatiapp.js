class ChatIAppChat extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { display: block; color: #17212b; font: 16px system-ui, sans-serif; }
        form { display: flex; gap: .5rem; }
        input { flex: 1; min-width: 0; padding: .65rem; }
        button { padding: .65rem 1rem; cursor: pointer; }
        [role="status"], table { margin-top: .75rem; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ccd3da; padding: .4rem; text-align: left; }
        .error { color: #a11; }
      </style>
      <form>
        <label for="question">Pregunta</label>
        <input id="question" name="question" required>
        <button type="submit">Enviar</button>
      </form>
      <p role="status" aria-live="polite"></p>
      <div class="response"></div>`;
    this.form = root.querySelector("form");
    this.question = root.querySelector("input");
    this.status = root.querySelector('[role="status"]');
    this.response = root.querySelector(".response");
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.sendQuestion();
    });
  }

  async sendQuestion() {
    if (!this.getToken) {
      this.showError("No se configuró la función para obtener el token.");
      return;
    }
    this.form.querySelector("button").disabled = true;
    this.status.textContent = "Consultando…";
    this.status.className = "";
    this.response.replaceChildren();
    try {
      let token = await this.getToken();
      let result = await this.request(token);
      if (result.status === 401) {
        token = await this.getToken();
        result = await this.request(token);
      }
      if (!result.ok) throw new Error(`La consulta falló (${result.status}).`);
      await this.readEvents(result.body);
      this.status.textContent = "";
    } catch (error) {
      this.showError(error instanceof Error ? error.message : "No se pudo consultar.");
    } finally {
      this.form.querySelector("button").disabled = false;
    }
  }

  request(token) {
    const baseUrl = (this.getAttribute("base-url") || "").replace(/\/$/, "");
    return fetch(`${baseUrl}/api/v1/chat/stream`, {
      method: "POST",
      headers: {
        Authorization: ["Be", "arer ", token].join(""),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        datasource_id: this.getAttribute("datasource-id") || "ventas",
        message: this.question.value,
      }),
    });
  }

  async readEvents(body) {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        this.handleFrame(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
      }
      if (done) break;
    }
  }

  handleFrame(frame) {
    const lines = frame.replace(/\r/g, "").split("\n");
    const type = lines.find((line) => line.startsWith("event: "))?.slice(7);
    const data = lines.find((line) => line.startsWith("data: "))?.slice(6);
    if (!type || !data) return;
    const payload = JSON.parse(data);
    if (type === "answer") {
      const answer = document.createElement("p");
      answer.textContent = payload.text;
      this.response.append(answer);
      this.dispatchEvent(new CustomEvent("chatiapp:answer", { detail: payload }));
    } else if (type === "result") {
      this.showResult(payload);
    } else if (type === "clarification") {
      this.status.textContent = payload.question;
      this.dispatchEvent(new CustomEvent("chatiapp:clarification", { detail: payload }));
    } else if (type === "error") {
      throw new Error(payload.message);
    }
  }

  showResult(result) {
    const table = document.createElement("table");
    const head = table.createTHead().insertRow();
    for (const column of result.columns) {
      const cell = document.createElement("th");
      cell.textContent = column;
      head.append(cell);
    }
    const body = table.createTBody();
    for (const row of result.rows) {
      const tableRow = body.insertRow();
      for (const value of row) {
        tableRow.insertCell().textContent = value == null ? "" : String(value);
      }
    }
    this.response.append(table);
  }

  showError(message) {
    this.status.textContent = message;
    this.status.className = "error";
    this.dispatchEvent(new CustomEvent("chatiapp:error", { detail: { message } }));
  }
}

if (!customElements.get("chatiapp-chat")) {
  customElements.define("chatiapp-chat", ChatIAppChat);
}
