import { useEffect, useState } from 'react';
import { onToast } from '../services/toast';

export default function ToastHost() {
  const [items, setItems] = useState([]);

  useEffect(() => {
    return onToast((t) => {
      setItems((prev) => [...prev, t]);
      setTimeout(() => setItems((prev) => prev.filter((x) => x.id !== t.id)), 5000);
    });
  }, []);

  if (items.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
      {items.map((t) => (
        <div
          key={t.id}
          className="pointer-events-auto bg-[#fc1c46] text-white px-4 py-3 rounded-lg shadow-lg text-sm max-w-sm"
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
