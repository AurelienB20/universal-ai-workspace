import { forwardStream } from "@/lib/backend";

export async function POST(request: Request) {
  return forwardStream(request, "/ask/stream");
}
