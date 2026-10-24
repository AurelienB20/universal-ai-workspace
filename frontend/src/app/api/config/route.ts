import { connection } from "next/server";

import { importsEnabled } from "@/lib/backend";

export async function GET() {
  // Read at request time: without it, this handler would be prerendered at build
  // time and keep the build machine's environment.
  await connection();
  return Response.json({ importsEnabled: importsEnabled() });
}
