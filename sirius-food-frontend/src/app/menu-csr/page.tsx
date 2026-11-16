"use client";

import { useEffect, useState } from "react";

import { MenuGrid } from "@/components/MenuGrid";
import { PUBLIC_API_URL, type MenuItem } from "@/lib/api";

type MenuState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; items: MenuItem[] };

export default function CsrMenuPage() {
  const [state, setState] = useState<MenuState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    async function loadMenu() {
      try {
        const response = await fetch(`${PUBLIC_API_URL}/menu/items`, {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const items: MenuItem[] = await response.json();
        if (!controller.signal.aborted) setState({ status: "ready", items });
      } catch {
        if (!controller.signal.aborted) setState({ status: "error" });
      }
    }

    void loadMenu();
    return () => controller.abort();
  }, [attempt]);

  return (
    <main className="page-shell csr-page" id="menu">
      <h1>Меню кампуса</h1>
      {state.status === "loading" && <p role="status">Загружаем меню…</p>}
      {state.status === "error" && (
        <section className="error-card">
          <p role="alert">Не удалось загрузить меню.</p>
          <button
            type="button"
            className="button button--dark"
            onClick={() => {
              setState({ status: "loading" });
              setAttempt((value) => value + 1);
            }}
          >
            Попробовать снова
          </button>
        </section>
      )}
      {state.status === "ready" && <MenuGrid items={state.items} />}
    </main>
  );
}
