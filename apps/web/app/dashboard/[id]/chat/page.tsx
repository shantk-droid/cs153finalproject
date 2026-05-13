import { ChatPanel } from "@/components/ChatPanel";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function ChatPage({ params }: Props) {
  const { id } = await params;
  return (
    <main className="mx-auto max-w-4xl space-y-4 px-6 py-8">
      <header>
        <p className="text-xs uppercase tracking-widest text-muted-foreground">Chat</p>
        <h1 className="text-2xl font-semibold tracking-tight">Ask the data</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Tool-using assistant grounded in your panel. Charts and tables render inline.
        </p>
      </header>
      <div className="min-h-[640px]">
        <ChatPanel datasetId={id} />
      </div>
    </main>
  );
}
