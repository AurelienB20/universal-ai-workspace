import { forward, notFound, suggestionsPath } from "@/lib/backend";

export async function GET(
  request: Request,
  ctx: RouteContext<"/api/repositories/[owner]/[name]/suggestions">,
) {
  const { owner, name } = await ctx.params;
  const language = new URL(request.url).searchParams.get("language");
  // Checked here so that nothing but a valid repository name reaches the backend path.
  const path = suggestionsPath(owner, name, language);
  return path === null ? notFound() : forward(request, path);
}
