import type { ArchitectureContent } from "@/i18n/architecture";

interface NodeProps {
  x: number;
  y: number;
  label: string;
  note?: string;
  accent?: boolean;
}

const NODE_WIDTH = 170;
const NODE_HEIGHT = 64;

function Node({ x, y, label, note, accent }: NodeProps) {
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={NODE_WIDTH}
        height={NODE_HEIGHT}
        rx={10}
        className={
          accent
            ? "fill-indigo-50 stroke-indigo-400 dark:fill-indigo-950 dark:stroke-indigo-500"
            : "fill-white stroke-zinc-300 dark:fill-zinc-900 dark:stroke-zinc-600"
        }
        strokeWidth={1.5}
      />
      <text
        x={x + NODE_WIDTH / 2}
        y={y + (note ? 27 : 37)}
        textAnchor="middle"
        className="fill-zinc-900 text-[15px] font-semibold dark:fill-zinc-100"
      >
        {label}
      </text>
      {note && (
        <text
          x={x + NODE_WIDTH / 2}
          y={y + 47}
          textAnchor="middle"
          className="fill-zinc-500 text-[12px] dark:fill-zinc-400"
        >
          {note}
        </text>
      )}
    </g>
  );
}

function Zone({
  x,
  width,
  label,
  className,
}: {
  x: number;
  width: number;
  label: string;
  className: string;
}) {
  return (
    <g>
      <rect
        x={x}
        y={10}
        width={width}
        height={340}
        rx={14}
        strokeDasharray="6 5"
        strokeWidth={1.5}
        className={className}
      />
      <text x={x + 14} y={32} className="fill-zinc-500 text-[12px] font-semibold uppercase dark:fill-zinc-400">
        {label}
      </text>
    </g>
  );
}

function FlowLabel({
  x,
  y,
  text,
  anchor = "middle",
}: {
  x: number;
  y: number;
  text: string;
  anchor?: "start" | "middle";
}) {
  return (
    <text x={x} y={y} textAnchor={anchor} className="fill-zinc-500 text-[11px] dark:fill-zinc-400">
      {text}
    </text>
  );
}

/** Components, trust zones and data flows. Colors follow the light and dark themes. */
export function ArchitectureDiagram({ content }: { content: ArchitectureContent["diagram"] }) {
  const { nodes, zones, flows, legend } = content;
  // Node positions (top-left corners).
  const browser = { x: 25, y: 70 };
  const github = { x: 25, y: 250 };
  const web = { x: 245, y: 70 };
  const api = { x: 465, y: 70 };
  const db = { x: 465, y: 250 };
  const voyage = { x: 705, y: 70 };
  const claude = { x: 705, y: 175 };
  const right = (n: { x: number }) => n.x + NODE_WIDTH;
  const middle = (n: { y: number }) => n.y + NODE_HEIGHT / 2;

  return (
    <figure className="flex flex-col gap-3">
      {/* Scrolls sideways on narrow screens rather than shrinking the text. */}
      <div className="overflow-x-auto">
        <svg
          viewBox="0 0 900 360"
          role="img"
          aria-label={content.title}
          className="min-w-[640px] text-zinc-400 dark:text-zinc-500"
        >
          <title>{content.title}</title>
          <defs>
            <marker
              id="arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
            </marker>
          </defs>

          <Zone
            x={10}
            width={200}
            label={zones.untrusted}
            className="fill-amber-50/70 stroke-amber-400 dark:fill-amber-950/30 dark:stroke-amber-700"
          />
          <Zone
            x={230}
            width={420}
            label={zones.server}
            className="fill-indigo-50/40 stroke-indigo-300 dark:fill-indigo-950/20 dark:stroke-indigo-800"
          />
          <Zone
            x={690}
            width={200}
            label={zones.providers}
            className="fill-zinc-50 stroke-zinc-300 dark:fill-zinc-900/40 dark:stroke-zinc-700"
          />

          <g stroke="currentColor" strokeWidth={1.8} fill="none" markerEnd="url(#arrow)">
            <line x1={right(browser)} y1={middle(browser)} x2={web.x - 4} y2={middle(web)} />
            <line x1={right(web)} y1={middle(web)} x2={api.x - 4} y2={middle(api)} />
            <line
              x1={api.x + NODE_WIDTH / 2}
              y1={api.y + NODE_HEIGHT}
              x2={db.x + NODE_WIDTH / 2}
              y2={db.y - 4}
            />
            <line x1={right(api)} y1={middle(api)} x2={voyage.x - 4} y2={middle(voyage)} />
            <path d={`M ${right(api)} ${middle(api) + 14} C 650 ${middle(api) + 14}, 650 ${middle(claude)}, ${claude.x - 4} ${middle(claude)}`} />
            <path d={`M ${api.x} ${middle(api) + 18} C 380 ${middle(api) + 18}, 300 ${middle(github)}, ${right(github) + 4} ${middle(github)}`} />
          </g>

          {/* The API key travels only between the two server components, above their
              arrow: the gap between the boxes is too narrow for the label. */}
          <text
            x={(right(web) + api.x) / 2}
            y={web.y - 10}
            textAnchor="middle"
            className="fill-indigo-600 text-[12px] font-semibold dark:fill-indigo-400"
          >
            X-API-Key
          </text>
          <FlowLabel x={(right(api) + voyage.x) / 2} y={middle(api) - 8} text={flows.embeddings} />
          <FlowLabel x={667} y={middle(claude) + 22} text={flows.answer} />
          <FlowLabel x={db.x + NODE_WIDTH / 2 + 8} y={(api.y + NODE_HEIGHT + db.y) / 2} text={flows.vectors} anchor="start" />
          <FlowLabel x={330} y={middle(github) - 4} text={flows.archive} />

          <Node {...browser} label={nodes.browser} />
          <Node {...github} label={nodes.github} />
          <Node {...web} label={nodes.web} note={nodes.webNote} accent />
          <Node {...api} label={nodes.api} note={nodes.apiNote} accent />
          <Node {...db} label={nodes.db} note={nodes.dbNote} accent />
          <Node {...voyage} label={nodes.voyage} />
          <Node {...claude} label={nodes.claude} />
        </svg>
      </div>
      <figcaption className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-zinc-500">
        <span>🔑 {legend.key}</span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded-sm border border-dashed border-amber-400 bg-amber-50 dark:border-amber-700 dark:bg-amber-950/40" />
          {legend.untrusted}
        </span>
      </figcaption>
    </figure>
  );
}
