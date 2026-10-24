import { forward } from "@/lib/backend";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(request: Request, ctx: RouteContext<"/api/imports/[id]">) {
  const { id } = await ctx.params;
  // Checked here so that nothing but a job ID is ever appended to the backend path.
  if (!UUID.test(id)) {
    return Response.json({ detail: "Import job not found." }, { status: 404 });
  }
  return forward(request, `/imports/${id}`);
}
