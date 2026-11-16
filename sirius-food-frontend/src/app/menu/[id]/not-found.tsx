import Link from "next/link";

export default function DishNotFound() {
  return (
    <main className="page-shell">
      <section className="error-card">
        <h1>Блюдо не найдено</h1>
        <p>В меню нет блюда с таким номером.</p>
        <Link className="button button--dark" href="/menu">К меню</Link>
      </section>
    </main>
  );
}
