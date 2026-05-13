"use client";

import { Bot, ChevronDown, ChevronRight, Loader2, Send, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { VegaLiteEmbed } from "@/components/VegaLiteEmbed";

type Role = "user" | "assistant";
type AgentName = "planner" | "forecaster" | "risk" | "buyer";

interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
  result?: unknown;
  duration_ms?: number;
  error?: string | null;
  status: "running" | "done";
}

interface AgentEvent {
  type: "router_decision" | "agent_start" | "agent_dispatch" | "agent_complete" | "cost_cap_hit";
  agent?: AgentName | "single";
  task?: string;
  summary?: string;
  rationale?: string;
  path?: "single" | "multi";
  specialist?: AgentName;
  from?: AgentName;
  to?: AgentName;
  sub_question?: string;
  spent_usd?: number;
  cap_usd?: number;
}

interface Message {
  role: Role;
  text: string;
  tool_calls: ToolCall[];
  agent_events: AgentEvent[];
  pending: boolean;
}

const QUICK_QUESTIONS: string[] = [
  "How many SKUs and what's my total annual revenue?",
  "Top 5 SKUs by revenue?",
  "What's my total inventory value and average days of cover?",
  "If lead times double for my top SKU, how much extra safety stock?",
  "Compare 90% vs 99% service level for my top SKU.",
  "Which SKUs are A-class and high-variance (Z)?",
];

interface Props {
  datasetId: string;
}

export function ChatPanel({ datasetId }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const scrollerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollerRef.current) scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
  }, [messages]);

  async function send(text: string) {
    if (!text.trim() || streaming) return;
    setInput("");
    const userMsg: Message = { role: "user", text, tool_calls: [], agent_events: [], pending: false };
    const assistantMsg: Message = { role: "assistant", text: "", tool_calls: [], agent_events: [], pending: true };
    setMessages((m) => [...m, userMsg, assistantMsg]);
    setStreaming(true);

    const turns = messages
      .filter((m) => m.role === "user" || (m.role === "assistant" && m.text.length > 0))
      .map((m) => ({ role: m.role, content: m.text }));
    turns.push({ role: "user", content: text });

    try {
      const r = await fetch(`/api/datasets/${encodeURIComponent(datasetId)}/chat`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ dataset_id: datasetId, messages: turns }),
      });
      if (!r.ok || !r.body) {
        const errText = await r.text();
        setMessages((m) => updateLast(m, (last) => ({
          ...last, text: `Error: ${r.status} ${errText.slice(0, 200)}`, pending: false,
        })));
        return;
      }
      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const events = buf.split("\n\n");
        buf = events.pop() ?? "";
        for (const ev of events) {
          const line = ev.trim();
          if (!line.startsWith("data:")) continue;
          let payload: any;
          try {
            payload = JSON.parse(line.slice(5).trim());
          } catch {
            continue;
          }
          handleEvent(payload, setMessages);
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setMessages((m) => updateLast(m, (last) => ({
        ...last, text: `Error: ${msg}`, pending: false,
      })));
    } finally {
      setStreaming(false);
      setMessages((m) => updateLast(m, (last) => ({ ...last, pending: false })));
    }
  }

  function handleEvent(ev: any, setM: typeof setMessages) {
    if (ev.type === "text_delta") {
      setM((m) => updateLast(m, (last) => ({ ...last, text: last.text + (ev.text ?? "") })));
    } else if (ev.type === "tool_call_start") {
      setM((m) => updateLast(m, (last) => ({
        ...last,
        tool_calls: [...last.tool_calls, { name: ev.name, arguments: ev.arguments ?? {}, status: "running" }],
      })));
    } else if (ev.type === "tool_call_result") {
      setM((m) => updateLast(m, (last) => ({
        ...last,
        tool_calls: last.tool_calls.map((tc, i, arr) =>
          i === arr.length - 1 && tc.name === ev.name && tc.status === "running"
            ? { ...tc, status: "done", result: ev.result, duration_ms: ev.duration_ms, error: ev.error }
            : tc,
        ),
      })));
    } else if (ev.type === "final") {
      setM((m) => updateLast(m, (last) => ({
        ...last,
        text: ev.text || last.text,
        pending: false,
      })));
    } else if (ev.type === "error") {
      setM((m) => updateLast(m, (last) => ({
        ...last, text: `Error: ${ev.message}`, pending: false,
      })));
    } else if (
      ev.type === "router_decision" ||
      ev.type === "agent_start" ||
      ev.type === "agent_dispatch" ||
      ev.type === "agent_complete" ||
      ev.type === "cost_cap_hit"
    ) {
      setM((m) => updateLast(m, (last) => ({
        ...last,
        agent_events: [...last.agent_events, ev as AgentEvent],
      })));
    }
  }

  return (
    <div className="flex h-full flex-col rounded-lg border bg-card">
      <header className="flex items-center justify-between border-b px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" aria-hidden />
          <h3 className="text-sm font-semibold">Chat</h3>
        </div>
        <p className="text-xs text-muted-foreground">claude-sonnet-4-6</p>
      </header>

      <div ref={scrollerRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Ask about forecasts, reorder recommendations, scenarios. Examples:
            </p>
            <div className="flex flex-wrap gap-1.5">
              {QUICK_QUESTIONS.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => send(q)}
                  className="rounded-full border bg-background px-2.5 py-1 text-xs hover:bg-accent"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <MessageBubble key={i} message={m} />
        ))}
      </div>

      <form
        className="flex gap-2 border-t p-3"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        aria-label="Chat with the inventory assistant"
      >
        <label htmlFor="chat-input" className="sr-only">
          Type your question
        </label>
        <input
          id="chat-input"
          type="text"
          value={input}
          placeholder="Ask about your inventory..."
          disabled={streaming}
          onChange={(e) => setInput(e.target.value)}
          className="h-9 flex-1 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={streaming || !input.trim()}
          aria-label={streaming ? "Sending" : "Send message"}
          className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        >
          {streaming ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Send className="h-3.5 w-3.5" aria-hidden />}
          Send
        </button>
      </form>
    </div>
  );
}

function updateLast(messages: Message[], fn: (m: Message) => Message): Message[] {
  if (messages.length === 0) return messages;
  const out = messages.slice();
  out[out.length - 1] = fn(out[out.length - 1]);
  return out;
}

function MessageBubble({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="ml-8 rounded-lg border bg-primary/5 px-3 py-2 text-sm">
        {message.text}
      </div>
    );
  }
  const charts = message.tool_calls.filter(
    (tc) => tc.status === "done" && (tc.result as any)?._render === "vega-lite",
  );
  return (
    <div className="space-y-2">
      {message.agent_events.length > 0 && (
        <AgentLane events={message.agent_events} />
      )}
      {message.tool_calls.length > 0 && (
        <div className="space-y-1">
          {message.tool_calls.map((tc, i) => (
            <ToolCallCard key={i} tc={tc} />
          ))}
        </div>
      )}
      {charts.map((tc, i) => {
        const r = tc.result as any;
        return (
          <VegaLiteEmbed key={`chart-${i}`} spec={r.spec} title={r.title} />
        );
      })}
      <div className="rounded-lg bg-muted/40 px-3 py-2 text-sm">
        {message.text ? (
          <MarkdownContent text={message.text} />
        ) : message.pending ? (
          <span className="italic text-muted-foreground">thinking…</span>
        ) : null}
      </div>
    </div>
  );
}

function MarkdownContent({ text }: { text: string }) {
  return (
    <div className="space-y-2 text-sm leading-relaxed text-foreground">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
          h1: ({ children }) => (
            <h2 className="mb-1 mt-3 text-base font-semibold tracking-tight">{children}</h2>
          ),
          h2: ({ children }) => (
            <h3 className="mb-1 mt-3 text-sm font-semibold tracking-tight">{children}</h3>
          ),
          h3: ({ children }) => (
            <h4 className="mb-1 mt-2 text-sm font-semibold tracking-tight">{children}</h4>
          ),
          ul: ({ children }) => (
            <ul className="my-2 list-disc space-y-1 pl-5 marker:text-muted-foreground">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="my-2 list-decimal space-y-1 pl-5 marker:text-muted-foreground">
              {children}
            </ol>
          ),
          li: ({ children }) => <li className="pl-1 leading-relaxed">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          em: ({ children }) => <em className="italic">{children}</em>,
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline-offset-4 hover:underline"
            >
              {children}
            </a>
          ),
          code: ({ className, children, ...props }) => {
            const inline = !/language-/.test(className ?? "");
            if (inline) {
              return (
                <code
                  className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em] text-foreground"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <code className={cn("font-mono text-[0.85em]", className)} {...props}>
                {children}
              </code>
            );
          },
          pre: ({ children }) => (
            <pre className="my-2 overflow-x-auto rounded-md border bg-background p-3 text-xs">
              {children}
            </pre>
          ),
          blockquote: ({ children }) => (
            <blockquote className="my-2 border-l-2 border-border pl-3 italic text-muted-foreground">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="my-3 border-border" />,
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto rounded-md border bg-background">
              <table className="w-full text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-muted/60 text-[11px] uppercase tracking-wider text-muted-foreground">
              {children}
            </thead>
          ),
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => <tr className="border-t first:border-t-0">{children}</tr>,
          th: ({ children, style }) => (
            <th
              className="whitespace-nowrap px-3 py-2 text-left font-medium"
              style={style}
            >
              {children}
            </th>
          ),
          td: ({ children, style }) => (
            <td
              className="whitespace-nowrap px-3 py-1.5 align-top"
              style={style}
            >
              {children}
            </td>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

const AGENT_PALETTE: Record<string, { label: string; color: string }> = {
  planner: { label: "Planner", color: "bg-indigo-500/10 text-indigo-700 dark:text-indigo-300 border-indigo-500/30" },
  forecaster: { label: "Forecaster", color: "bg-blue-500/10 text-blue-700 dark:text-blue-300 border-blue-500/30" },
  risk: { label: "Risk", color: "bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/30" },
  buyer: { label: "Buyer", color: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30" },
};

function AgentLane({ events }: { events: AgentEvent[] }) {
  const [open, setOpen] = useState(true);
  const routerEvent = events.find((e) => e.type === "router_decision");
  return (
    <div className="rounded-md border bg-muted/30 text-xs">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left"
      >
        <span className="flex items-center gap-1.5 font-medium text-foreground">
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          <Bot className="h-3 w-3 text-primary" aria-hidden />
          Agents
          {routerEvent?.path === "multi" ? (
            <span className="ml-1 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
              multi-agent
            </span>
          ) : routerEvent?.path === "single" ? (
            <span className="ml-1 rounded bg-muted-foreground/10 px-1.5 py-0.5 text-[10px] text-muted-foreground">
              single-agent
            </span>
          ) : null}
        </span>
      </button>
      {open && (
        <div className="space-y-1 border-t px-2.5 py-2">
          {events.map((e, i) => (
            <AgentEventRow key={i} event={e} />
          ))}
        </div>
      )}
    </div>
  );
}

function AgentEventRow({ event }: { event: AgentEvent }) {
  if (event.type === "router_decision") {
    return (
      <div className="text-muted-foreground">
        <span className="font-medium">Router:</span> {event.rationale ?? `→ ${event.path}`}
      </div>
    );
  }
  const agent = event.agent ?? event.to ?? "planner";
  const palette = AGENT_PALETTE[agent] ?? AGENT_PALETTE.planner;
  if (event.type === "agent_start") {
    return (
      <div className="flex items-start gap-1.5">
        <span className={cn("inline-flex shrink-0 rounded border px-1.5 py-0.5 text-[10px]", palette.color)}>{palette.label}</span>
        <span className="text-muted-foreground">starting{event.task ? `: ${event.task.slice(0, 120)}` : "…"}</span>
      </div>
    );
  }
  if (event.type === "agent_dispatch") {
    const toPalette = AGENT_PALETTE[event.to ?? "planner"] ?? AGENT_PALETTE.planner;
    return (
      <div className="flex items-start gap-1.5">
        <span className={cn("inline-flex shrink-0 rounded border px-1.5 py-0.5 text-[10px]", palette.color)}>{palette.label}</span>
        <span className="shrink-0 text-muted-foreground">→</span>
        <span className={cn("inline-flex shrink-0 rounded border px-1.5 py-0.5 text-[10px]", toPalette.color)}>{toPalette.label}</span>
        <span className="text-muted-foreground">{event.sub_question?.slice(0, 120) ?? ""}</span>
      </div>
    );
  }
  if (event.type === "agent_complete") {
    return (
      <div className="flex items-start gap-1.5">
        <span className={cn("inline-flex shrink-0 rounded border px-1.5 py-0.5 text-[10px]", palette.color)}>{palette.label}</span>
        <span className="text-muted-foreground">done — {event.summary?.slice(0, 200) ?? "(no summary)"}</span>
      </div>
    );
  }
  if (event.type === "cost_cap_hit") {
    return (
      <div className="rounded bg-amber-500/10 px-1.5 py-1 text-amber-700 dark:text-amber-300">
        budget ceiling reached: ${event.spent_usd?.toFixed(2) ?? "?"} / ${event.cap_usd?.toFixed(2) ?? "?"}
      </div>
    );
  }
  return null;
}


function ToolCallCard({ tc }: { tc: ToolCall }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md border border-dashed bg-muted/20 text-xs">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left"
      >
        <span className="flex items-center gap-1.5">
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          <span className="font-mono">{tc.name}</span>
          {tc.status === "running" ? (
            <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" aria-hidden />
          ) : tc.error ? (
            <span className="rounded bg-destructive/10 px-1 py-0.5 text-destructive">error</span>
          ) : (
            <span className="text-muted-foreground">{tc.duration_ms}ms</span>
          )}
        </span>
      </button>
      {open && (
        <div className="space-y-1 border-t px-2 py-1.5">
          <details>
            <summary className="cursor-pointer text-muted-foreground">arguments</summary>
            <pre className="mt-1 max-h-40 overflow-auto rounded bg-background p-2 font-mono text-[11px]">
              {JSON.stringify(tc.arguments, null, 2)}
            </pre>
          </details>
          {tc.result !== undefined && (
            <details>
              <summary className="cursor-pointer text-muted-foreground">result</summary>
              <pre className="mt-1 max-h-60 overflow-auto rounded bg-background p-2 font-mono text-[11px]">
                {JSON.stringify(tc.result, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
