import { Header } from "@/components/Header";
import { HomeIntro } from "@/components/HomeIntro";
import { Workspace } from "@/components/Workspace";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8 sm:py-12">
      <Header />
      <HomeIntro />
      <Workspace />
    </main>
  );
}
