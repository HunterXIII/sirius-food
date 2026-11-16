import { DishCard } from "@/components/DishCard";
import type { MenuItem } from "@/lib/api";

export function MenuGrid({ items }: { items: MenuItem[] }) {
  if (items.length === 0) {
    return <p className="empty-state">В меню пока нет блюд.</p>;
  }

  return (
    <div className="dish-grid">
      {items.map((item) => <DishCard key={item.id} item={item} />)}
    </div>
  );
}
