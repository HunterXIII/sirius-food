export default function MenuLoading() {
  return (
    <main className="page-shell loading-page" aria-busy="true">
      <h1 role="status">Загружаем меню…</h1>
      <div className="loading-grid" aria-hidden="true">
        {Array.from({ length: 6 }, (_, index) => (
          <div className="loading-card" key={index}>
            <div className="loading-card__art shimmer" />
            <div className="loading-card__line shimmer" />
            <div className="loading-card__line loading-card__line--short shimmer" />
          </div>
        ))}
      </div>
    </main>
  );
}
