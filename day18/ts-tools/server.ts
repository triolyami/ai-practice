// Демо MCP-сервер на TypeScript (stdio): зеркало py-tools из tools_server.py —
// те же инструменты и те же русские описания, чтобы по списку /api/mcp было
// видно, что для клиента язык сервера невидим.
// stdout зарезервирован под JSON-RPC — логи только в console.error (stderr).
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const server = new McpServer({ name: "ts-tools", version: "0.1.0" });

const NOTES: string[] = [];

const text = (s: string) => ({ content: [{ type: "text" as const, text: s }] });

server.registerTool(
  "server_time",
  {
    description: "Текущее время сервера и дата (ГГГГ-ММ-ДД ЧЧ:ММ:СС)",
    inputSchema: {},
  },
  async () => {
    const pad = (n: number) => String(n).padStart(2, "0");
    const d = new Date();
    const stamp =
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
      `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    return text(stamp);
  },
);

server.registerTool(
  "add",
  {
    description: "Сложить два числа",
    inputSchema: { a: z.number(), b: z.number() },
  },
  async ({ a, b }) => text(String(a + b)),
);

server.registerTool(
  "echo",
  {
    description: "Вернуть строку как есть — проверка round-trip аргументов",
    inputSchema: { text: z.string() },
  },
  async ({ text: t }) => text(t),
);

server.registerTool(
  "notes_list",
  {
    description: "Список заметок из in-memory хранилища сервера",
    inputSchema: {},
  },
  async () => ({
    content: [{ type: "text" as const, text: JSON.stringify(NOTES) }],
    structuredContent: { result: NOTES },
  }),
);

server.registerTool(
  "notes_add",
  {
    description: "Добавить заметку и вернуть её номер",
    inputSchema: { text: z.string() },
  },
  async ({ text: t }) => {
    NOTES.push(t);
    return text(`заметка #${NOTES.length} сохранена`);
  },
);

await server.connect(new StdioServerTransport());
console.error("[ts-tools] listening on stdio");
