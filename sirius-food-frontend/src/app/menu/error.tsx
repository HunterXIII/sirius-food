"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

export default function MenuError({ reset }: { reset: () => void }) {
  const router = useRouter();
  const [retrying, startTransition] = useTransition();

  return (
    <main className="page-shell">
      <section className="error-card">
        <h1>Не удалось загрузить меню</h1>
        <p>Сервис меню временно недоступен. Попробуйте ещё раз.</p>
        <button
          type="button"
          className="button button--dark"
          disabled={retrying}
          onClick={() => startTransition(() => {
            router.refresh();
            reset();
          })}
        >
          {retrying ? "Загружаем…" : "Попробовать снова"}
        </button>
      </section>
    </main>
  );
}
