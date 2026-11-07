import { useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { updateSession } from "@/api/generated/sdk.gen";
import type { DiscoveryResult } from "@/api/generated/types.gen";
import { DiscoveryView } from "@/components/home/discovery";
import { HelixBackdrop } from "@/components/home/helix-backdrop";
import { Footer, Page, TopBar } from "@/components/layout/top-bar";
import { Button } from "@/components/ui/button";
import { ErrorBox, Panel } from "@/components/ui/card";
import { Label, Textarea } from "@/components/ui/input";
import { errorMessage, unwrap } from "@/lib/api";
import { useAgentAvailable, useCollect, useCreateSession } from "@/lib/queries";
import { rememberSession } from "@/lib/storage";
import { guessGenes } from "@/lib/ui-state";
import { useSse } from "@/lib/useSse";

const EXAMPLES = [
  "Is IL17A higher in psoriasis lesional skin than in non-lesional skin?",
  "Is GPC3 higher in hepatocellular carcinoma than in adjacent normal liver?",
  "Does IFN-gamma treatment raise CXCL9 and CXCL10 in pancreatic cancer cell lines?",
];

export function HomePage() {
  const navigate = useNavigate();
  const agent = useAgentAvailable();
  const [question, setQuestion] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [genes, setGenes] = useState<string[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [answers, setAnswers] = useState<string[]>([]);
  const [phase, setPhase] = useState<"ask" | "work">("ask");
  const create = useCreateSession();
  const sse = useSse<DiscoveryResult>();
  const collect = useCollect(sessionId ?? "");

  useEffect(() => {
    document.title = "cell ledger";
  }, []);

  useEffect(() => {
    if (sse.result) {
      setGenes((g) => (g.length ? g : (sse.result?.genes ?? [])));
      setSelected(new Set((sse.result.candidates ?? []).slice(0, 4).map((c) => c.gse)));
    }
  }, [sse.result]);

  const ensureSession = async (): Promise<string> => {
    if (sessionId) return sessionId;
    const info = await create.mutateAsync();
    setSessionId(info.id);
    rememberSession(info.id);
    return info.id;
  };

  const submit = async () => {
    const q = question.trim();
    if (!q) return;
    const id = await ensureSession();
    setPhase("work");
    setGenes(guessGenes(q));
    void sse.start(`/api/sessions/${id}/discover`, { question: q });
  };

  const answer = async (reply: string) => {
    if (!sessionId) return;
    const all = [...answers, reply.trim()].filter(Boolean);
    setAnswers(all);
    // The question stays as typed; the answers ride along as their own field.
    void sse.start(`/api/sessions/${sessionId}/discover`, {
      question: question.trim(),
      answers: all,
    });
  };

  const [saveError, setSaveError] = useState<string | null>(null);
  const startCollect = async (gses: string[]) => {
    const id = await ensureSession();
    // The design step reads this state (the interpretation, the clarifications, the genes), so
    // it must be on the session before a download can finish and trigger a design. The
    // question stays as typed; clarifications ride along in state.
    const state = {
      discovery: sse.result ?? null,
      genes,
      selected: gses,
      answers: answers.join("\n") || undefined,
    };
    setSaveError(null);
    try {
      unwrap(
        await updateSession({
          path: { session_id: id },
          body: { question: question.trim() || null, state },
        }),
      );
    } catch (e) {
      setSaveError(errorMessage(e));
      return;
    }
    await collect.mutateAsync(gses);
    void navigate({ to: "/s/$sessionId", params: { sessionId: id } });
  };

  const busy = create.isPending || sse.status === "streaming";

  return (
    <>
      <HelixBackdrop />
      <TopBar sessionId={sessionId ?? undefined} glass />
      <Page>
        <div className="pt-4">
          <p className="text-[13px] text-ink-2">A specialist for public RNA-seq data</p>
          <h1 className="mt-2 max-w-[26ch]">Ask a question a dataset can answer.</h1>
          <p className="mt-4 max-w-[64ch] text-ink-2">
            cell ledger searches NCBI GEO for bulk RNA-seq studies that can bear the question,
            labels each sample from the published record with its evidence in hand, and runs a
            single reproducible comparison. Every figure it reports leads back to a file.
          </p>
        </div>

        <Panel className="glass glass-clear mt-8 p-5">
          <Label htmlFor="question">Your question</Label>
          <Textarea
            id="question"
            rows={3}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit();
            }}
            placeholder="Is gene X higher in cell type Y in disease Z?"
            className="mt-1.5 text-[16px]"
            disabled={phase === "work" && busy}
          />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-1.5">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => setQuestion(ex)}
                  className="h-7 rounded-md border border-line-2 bg-surface-2 px-2.5 text-[12px] text-ink-2 hover:border-accent hover:text-ink"
                >
                  {ex.length > 52 ? `${ex.slice(0, 50)}…` : ex}
                </button>
              ))}
            </div>
            <Button
              variant="primary"
              size="lg"
              onClick={() => void submit()}
              disabled={!question.trim() || busy || !agent.data}
            >
              Find datasets
            </Button>
          </div>
          {agent.isSuccess && !agent.data && (
            <p className="mt-3 text-[13px] text-amber">
              This server has no Claude key configured, so it cannot search for datasets or design
              the analysis. Set CELL_LEDGER_ANTHROPIC_API_KEY and restart the API.
            </p>
          )}
          {create.isError && (
            <div className="mt-3">
              <ErrorBox title="Could not start a session">{errorMessage(create.error)}</ErrorBox>
            </div>
          )}
        </Panel>

        {phase === "work" && sessionId && (
          <div className="mt-6">
            <DiscoveryView
              result={sse.result}
              feed={sse.feed}
              streaming={sse.status === "streaming"}
              error={sse.error}
              genes={genes}
              onGenesChange={setGenes}
              selected={selected}
              onToggle={(gse) =>
                setSelected((s) => {
                  const n = new Set(s);
                  if (n.has(gse)) n.delete(gse);
                  else n.add(gse);
                  return n;
                })
              }
              onAnswer={(a) => void answer(a)}
              onCollect={() => void startCollect([...selected])}
              collecting={collect.isPending}
            />
            {saveError && (
              <div className="mt-3">
                <ErrorBox title="Could not save what the search settled">
                  {saveError}. Nothing was downloaded; try again.
                </ErrorBox>
              </div>
            )}
            {collect.isError && (
              <div className="mt-3">
                <ErrorBox title="Could not start the downloads">
                  {errorMessage(collect.error)}
                </ErrorBox>
              </div>
            )}
          </div>
        )}

        <Footer />
      </Page>
    </>
  );
}
