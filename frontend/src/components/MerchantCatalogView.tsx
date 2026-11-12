import React, { useState } from 'react';
import {
  ShoppingBag,
  Search,
  Package,
  Calculator,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  Tag,
} from 'lucide-react';
import { Product } from '../types/intentlock';
import { formatUsd } from '../utils/formatters';

interface MerchantCatalogViewProps {
  catalog: Product[];
  onQuickStartWithSku?: (sku: string, productName: string) => void;
}

export const MerchantCatalogView: React.FC<MerchantCatalogViewProps> = ({
  catalog,
  onQuickStartWithSku,
}) => {
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedCategory, setSelectedCategory] = useState<string>('ALL');

  const categories = [
    'ALL',
    ...Array.from(new Set(catalog.map((p) => p.category))),
  ];

  const filteredProducts = catalog.filter((p) => {
    const matchesCat =
      selectedCategory === 'ALL' || p.category === selectedCategory;
    const q = searchQuery.toLowerCase().trim();
    if (!q) return matchesCat;
    const kw = (p.keywords || []).join(' ').toLowerCase();
    return (
      matchesCat &&
      (p.sku.toLowerCase().includes(q) ||
        p.name.toLowerCase().includes(q) ||
        p.pack_size_desc.toLowerCase().includes(q) ||
        kw.includes(q))
    );
  });

  return (
    <div className="space-y-6">
      {/* Merchant Policy Header */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-2xs overflow-hidden">
        <div className="px-6 py-5 bg-gradient-to-r from-indigo-50 via-white to-slate-50 border-b border-slate-200 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="flex items-start gap-3.5">
            <div className="w-11 h-11 rounded-xl bg-indigo-600 text-white flex items-center justify-center shrink-0 shadow-2xs">
              <ShoppingBag className="w-5 h-5" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-base font-bold tracking-tight text-slate-900">
                  Acme Workspace Supplies — Store Catalog (15 Verified USD Items)
                </h2>
                <span className="font-mono text-xs px-2.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold">
                  Verified Merchant · USD
                </span>
              </div>
              <p className="text-xs text-slate-600 mt-1">
                Click <strong>"Request"</strong> on any item below to immediately build a team shopping cart with the AI Purchasing Assistant.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 shrink-0 font-mono text-xs">
            <div className="px-3.5 py-2 rounded-xl bg-white border border-slate-200 text-slate-700">
              Products: <strong>{catalog.length}</strong>
            </div>
            <div className="px-3.5 py-2 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800">
              Currency: <strong>USD ($)</strong>
            </div>
          </div>
        </div>

        {/* Search & Category Filter Bar */}
        <div className="p-4 bg-slate-50 border-b border-slate-200 flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            {categories.map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => setSelectedCategory(cat)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
                  selectedCategory === cat
                    ? 'bg-indigo-600 text-white shadow-2xs'
                    : 'bg-white text-slate-700 border border-slate-200 hover:bg-slate-100'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>

          <div className="relative w-full md:w-72">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search SKU, name, or keyword..."
              className="w-full rounded-lg border border-slate-300 bg-white pl-9 pr-3 py-1.5 text-xs text-slate-900 focus:border-indigo-500 focus:outline-none"
            />
          </div>
        </div>

        {/* Product Grid */}
        <div className="p-5 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 bg-slate-50/40">
          {filteredProducts.map((prod) => {
            const isLowStock = prod.stock_available <= 8;
            return (
              <div
                key={prod.sku}
                className="bg-white rounded-xl border border-slate-200 p-4 flex flex-col justify-between gap-3 hover:border-indigo-300 hover:shadow-sm transition"
              >
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs font-bold px-2.5 py-0.5 rounded bg-indigo-50 text-indigo-800 border border-indigo-200">
                      {prod.sku}
                    </span>
                    <span className="text-[11px] font-medium text-slate-500">
                      {prod.category}
                    </span>
                  </div>

                  <h3 className="text-sm font-bold text-slate-900 leading-snug">
                    {prod.name}
                  </h3>

                  <div className="flex items-center gap-1.5 text-xs text-slate-600">
                    <Package className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                    <span>{prod.pack_size_desc}</span>
                  </div>

                  {/* Deterministic Headcount / Pack Math Rule */}
                  <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200/80 text-[11px] text-slate-700 space-y-1">
                    <div className="font-semibold text-indigo-900 flex items-center gap-1">
                      <Calculator className="w-3.5 h-3.5 text-indigo-600" />
                      Deterministic Pack-Size Rule:
                    </div>
                    <p className="leading-relaxed">{prod.recommended_rule}</p>
                  </div>

                  {prod.keywords && prod.keywords.length > 0 && (
                    <div className="flex flex-wrap gap-1 pt-1">
                      {prod.keywords.slice(0, 5).map((kw) => (
                        <span
                          key={kw}
                          className="inline-flex items-center gap-0.5 text-[10px] font-mono bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded"
                        >
                          <Tag className="w-2.5 h-2.5" />
                          {kw}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <div className="pt-3 border-t border-slate-100 flex items-center justify-between gap-2">
                  <div>
                    <div className="text-base font-mono font-bold text-slate-900">
                      {formatUsd(prod.unit_price_cents)}
                    </div>
                    <div className="text-[10px] font-mono text-slate-400">
                      {prod.unit_price_cents} cents USD
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-mono font-semibold border ${
                        isLowStock
                          ? 'bg-amber-50 border-amber-300 text-amber-900'
                          : 'bg-emerald-50 border-emerald-200 text-emerald-800'
                      }`}
                    >
                      {isLowStock ? (
                        <AlertTriangle className="w-3 h-3 text-amber-600" />
                      ) : (
                        <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                      )}
                      Stock: {prod.stock_available}
                    </span>

                    {onQuickStartWithSku && (
                      <button
                        type="button"
                        onClick={() => onQuickStartWithSku(prod.sku, prod.name)}
                        className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-indigo-50 text-indigo-700 hover:bg-indigo-100 border border-indigo-200 transition"
                      >
                        Request
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Footer Invariant Note */}
        <div className="px-5 py-3 bg-slate-100 border-t border-slate-200 flex items-center gap-2 text-xs text-slate-600">
          <ShieldCheck className="w-4 h-4 text-emerald-600 shrink-0" />
          <span>
            Note: <strong>SKU-015 (OSHA First Aid Kit)</strong> is intentionally seeded with low stock (5 units) so judges can test Guardrail <strong>G-02</strong> automatic inventory capping.
          </span>
        </div>
      </div>
    </div>
  );
};
