import { forward } from "@/lib/backend";

export async function GET(request: Request) {
  return forward(request, "/repositories");
}
