import { forward } from "@/lib/backend";

export async function POST(request: Request) {
  return forward(request, "/imports");
}
