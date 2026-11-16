import type { Metadata } from "next";

import { MenuGrid } from "@/components/MenuGrid";
import { getMenuItems } from "@/lib/api";

export const metadata: Metadata = {
  title: "Меню",
  description: "Блюда кампуса «Сириус.Еда», цены и наличие.",
};

export const revalidate = 60;

export default async function MenuPage() {
  const items = await getMenuItems();

  return (
    <main className="page-shell csr-page" id="menu">
      <h1>Меню кампуса</h1>
      <MenuGrid items={items} />
    </main>
  );
}
