# Browser Automation & ATS Autofill Protocol

Este módulo documenta cómo conectar **Claude Code** (o cualquier agente basado en LLM) a una instancia real de **Brave / Chromium** usando un perfil persistente para buscar empleo en portales internacionales (Himalayas, Arc.dev, Real Work From Anywhere, Remote Rocketship) y rellenar automáticamente formularios de postulación en ATS (Greenhouse, Lever, Ashby).

---

## 1. ¿Por qué usar un Perfil Persistente de Navegador?

1. **Persistencia de Sesión:** Inicias sesión manualmente una sola vez en LinkedIn, Himalayas, Google o Arc.dev. Las cookies y tokens de autenticación se mantienen para siempre.
2. **Evasión de Bot Detection:** Al usar tu navegador real con tu IP residencial, los portales no te bloquean con Cloudflare ni CAPTCHAs que suelen fallar en navegadores headless.
3. **Visibilidad en Tiempo Real:** Puedes ver en tu pantalla cómo el agente interactúa con la página, hace clic y rellena los campos.

---

## 2. Puesta en Marcha

### Paso 1: Lanzar el Navegador con Perfil Dedicado

Ejecuta en tu terminal:

```bash
# Para Brave en Linux:
brave --user-data-dir="$HOME/.config/brave-jobhunt" --remote-debugging-port=9222 &

# O para Chromium:
chromium --user-data-dir="$HOME/.config/chromium-jobhunt" --remote-debugging-port=9222 &
```

*Inicia sesión en tus portales preferidos (LinkedIn, Arc, Himalayas).*

---

### Paso 2: Conectar con Claude Code vía MCP

Agrega el servidor MCP oficial de Puppeteer en Claude Code:

```bash
claude mcp add puppeteer -s user npx -y @modelcontextprotocol/server-puppeteer
```

O configúralo en tu archivo `~/.claude.json`:

```json
{
  "mcpServers": {
    "browser": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
      "env": {
        "PUPPETEER_EXECUTABLE_PATH": "/usr/bin/brave"
      }
    }
  }
}
```

---

## 3. Protocolo de Autofill (Human-in-the-Loop)

Para evitar enviar información errónea en preguntas eliminatorias, el flujo recomendado es:

1. **Extracción y Diagnóstico:** El agente navega a la oferta de trabajo y extrae los requisitos con `scrape_job`.
2. **Selección del Track y Compilación:** Selecciona el track más afín (Backend, Fullstack, Systems, AI, Data) y compila el PDF de 1 página.
3. **Relleno Automático:** El agente hace clic en "Apply" y rellena los campos estándar de Greenhouse/Lever/Ashby mapeados en `autofill_config.json`.
4. **Adjuntar CV:** Sube el PDF compilado al input de tipo archivo.
5. **Revisión Humana:** El agente te avisa: *"Formulario completado. Por favor revisa la pantalla y presiona Submit cuando estés listo"*.
