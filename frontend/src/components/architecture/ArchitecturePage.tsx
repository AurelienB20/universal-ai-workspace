"use client";

import Link from "next/link";

import { REPOSITORY_URL, architecture, codeUrl } from "@/i18n/architecture";
import { useLanguage } from "@/i18n/language";

import { ArchitectureDiagram } from "./ArchitectureDiagram";
import { PipelineExplorer } from "./PipelineExplorer";

/** "How it is built": each step, each architecture choice, and what it costs. */
export function ArchitecturePage() {
  const { language } = useLanguage();
  const content = architecture[language];
  const { hero, pipeline, diagram, decisions, safeguards, metrics } = content;

  return (
    <div className="flex flex-col gap-12">
      <section className="flex flex-col gap-4">
        <p className="text-xs font-semibold tracking-wide text-indigo-600 uppercase dark:text-indigo-400">
          {hero.eyebrow}
        </p>
        <h2 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
          {hero.title}
        </h2>
        <p className="max-w-2xl text-zinc-600 dark:text-zinc-400">{hero.intro}</p>
        <div className="flex flex-wrap gap-3">
          <Link href="/" className="button-primary">
            {hero.tryDemo}
          </Link>
          <a
            href={REPOSITORY_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="button-secondary"
          >
            {hero.sourceCode} ↗
          </a>
        </div>
      </section>

      <Section heading={pipeline.heading} intro={pipeline.intro}>
        <PipelineExplorer content={pipeline} />
      </Section>

      <Section heading={diagram.heading} intro={diagram.intro}>
        <ArchitectureDiagram content={diagram} />
      </Section>

      <Section heading={decisions.heading} intro={decisions.intro}>
        <div className="grid gap-4 md:grid-cols-2">
          {decisions.items.map((item) => (
            <article key={item.title} className="card flex flex-col gap-3">
              <h3 className="font-semibold">{item.title}</h3>
              <p className="text-sm font-medium">{item.decision}</p>
              <dl className="flex flex-col gap-2 text-sm">
                <Term label={decisions.labels.why} text={item.why} />
                <Term label={decisions.labels.tradeoff} text={item.tradeoff} />
                <Term label={decisions.labels.revisit} text={item.revisit} />
              </dl>
              <a
                href={codeUrl(item.code)}
                target="_blank"
                rel="noopener noreferrer"
                className="link mt-auto text-xs"
              >
                {decisions.labels.code} ↗
              </a>
            </article>
          ))}
        </div>
      </Section>

      <Section heading={safeguards.heading} intro={safeguards.intro}>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {safeguards.items.map((item) => (
            <li
              key={item.title}
              className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
            >
              <h3 className="mb-1 text-sm font-semibold">{item.title}</h3>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">{item.text}</p>
            </li>
          ))}
        </ul>
      </Section>

      <Section heading={metrics.heading} intro={metrics.intro}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <tbody>
              {metrics.rows.map((row) => (
                <tr key={row.label} className="border-b border-zinc-200 dark:border-zinc-800">
                  <th scope="row" className="py-2 pr-4 text-left font-medium">
                    {row.label}
                  </th>
                  <td className="py-2 text-zinc-700 dark:text-zinc-300">{row.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="notice mt-3">{metrics.caveat}</p>
      </Section>
    </div>
  );
}

function Section({
  heading,
  intro,
  children,
}: {
  heading: string;
  intro: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-4">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">{heading}</h2>
        <p className="mt-1 text-zinc-600 dark:text-zinc-400">{intro}</p>
      </div>
      {children}
    </section>
  );
}

function Term({ label, text }: { label: string; text: string }) {
  return (
    <div>
      <dt className="text-xs font-semibold tracking-wide text-zinc-500 uppercase">{label}</dt>
      <dd className="text-zinc-700 dark:text-zinc-300">{text}</dd>
    </div>
  );
}
