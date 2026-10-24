import { forward, importsEnabled, notFound } from "@/lib/backend";

export async function POST(request: Request) {
  if (!importsEnabled()) return notFound();
  return forward(request, "/imports");
}
