import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AddToCartButton } from "@/components/AddToCartButton";
import { DishArtwork } from "@/components/DishArtwork";
import { formatPrice, getMenuItem } from "@/lib/api";
import { presentDish } from "@/lib/presentation";

type PageProps = {
  params: Promise<{ id: string }>;
};

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  const item = await getMenuItem(id);
  if (!item) notFound();

  const description = `${item.name} в меню «Сириус.Еды». Цена — ${formatPrice(item.price)}.`;
  const path = `/menu/${item.id}`;

  return {
    title: item.name,
    description,
    alternates: { canonical: path },
    openGraph: {
      type: "website",
      title: item.name,
      description,
      url: path,
    },
  };
}

export default async function MenuItemPage({ params }: PageProps) {
  const { id } = await params;
  const item = await getMenuItem(id);
  if (!item) notFound();

  const art = presentDish(item);
  const available = item.is_available !== false;

  return (
    <main className="page-shell detail-page">
      <div className="breadcrumbs">
        <Link href="/menu">Меню</Link>
        <span aria-hidden="true">/</span>
        <span>{item.name}</span>
      </div>
      <article className="detail-card">
        <div className="detail-card__art">
          <DishArtwork {...art} category={item.category ?? "Меню"} />
        </div>
        <div className="detail-card__info">
          <h1>{item.name}</h1>
          <div className="detail-price-row">
            <strong className="detail-price">{formatPrice(item.price)}</strong>
            <span className={available ? "availability" : "availability availability--no"}>
              <i aria-hidden="true" />
              {available ? "В наличии" : "Нет в наличии"}
            </span>
          </div>
          <AddToCartButton available={available} />
        </div>
      </article>
      <Link className="back-link" href="/menu">← Назад к меню</Link>
    </main>
  );
}
