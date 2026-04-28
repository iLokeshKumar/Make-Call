"use client";

import { useEffect, useState, useCallback } from "react";
import { Package, Plus, Trash2, Edit, Save, X, ChevronDown, ChevronUp, Tag, Layers } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useRouter } from "next/navigation";
import Pagination from "@/components/Pagination";

import { apiFetch } from "@/utils/apiFetch";
interface Product {
    id?: number;
    name: string;
    sku?: string;
    stock: number;
    price: string;
    currency?: string;
    note?: string;
    is_active?: boolean;
    // Catalog
    brand?: string;
    category?: string;
    subcategory?: string;
    product_line?: string;
    model_number?: string;
    description?: string;
    // Pricing
    mrp?: string;
    cost_price?: string;
    min_price?: string;
    // Tax / compliance
    hsn_code?: string;
    tax_rate?: string;
    unit?: string;
    // Logistics
    reorder_level?: number | string;
    warranty_months?: number | string;
    // Media
    image_url?: string;
}

const EMPTY_FORM: Product = {
    name: "", sku: "", stock: 0, price: "", currency: "INR", note: "",
    brand: "", category: "", subcategory: "", product_line: "", model_number: "",
    description: "", mrp: "", cost_price: "", min_price: "",
    hsn_code: "", tax_rate: "", unit: "", reorder_level: "", warranty_months: "", image_url: "" };

const inputCls = "w-full rounded-xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-800/60 backdrop-blur-sm px-3 py-2.5 text-sm text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-violet-400 shadow-sm";
const labelCls = "text-xs font-bold text-slate-600 dark:text-slate-400 uppercase tracking-wide";

function FieldGroup({ title, children }: { title: string; children: React.ReactNode }) {
    const [open, setOpen] = useState(true);
    return (
        <div className="border border-slate-100 dark:border-white/10 rounded-xl overflow-hidden">
            <button
                type="button"
                onClick={() => setOpen(v => !v)}
                className="w-full flex items-center justify-between px-4 py-2.5 bg-slate-50 dark:bg-slate-800/40 text-left"
            >
                <span className="text-xs font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">{title}</span>
                {open ? <ChevronUp className="h-3.5 w-3.5 text-slate-400" /> : <ChevronDown className="h-3.5 w-3.5 text-slate-400" />}
            </button>
            {open && <div className="px-4 py-3 space-y-3">{children}</div>}
        </div>
    );
}

export default function InventoryPage() {
    const { user, isLoading, sessionTimeout } = useAuth();
    const router = useRouter();
    const [products, setProducts] = useState<Product[]>([]);
    const [loading, setLoading] = useState(true);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingProduct, setEditingProduct] = useState<Product | null>(null);
    const [formData, setFormData] = useState<Product>(EMPTY_FORM);

    const [currentPage, setCurrentPage] = useState(1);
    const [totalProducts, setTotalProducts] = useState(0);
    const [itemsPerPage] = useState(10);
    const totalPages = Math.ceil(totalProducts / itemsPerPage);

    const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";
    const CRM_BASE = `${API_BASE}/crm`;

    const fetchInventory = useCallback(async (page: number = 1) => {
        setLoading(true);
        try {
            const res = await apiFetch(`${CRM_BASE}/inventory?page=${page}&limit=${itemsPerPage}`, {
            });
            if (res.status === 401) { sessionTimeout(); return; }
            const data = await res.json();
            setProducts(data.items || []);
            setTotalProducts(data.total || 0);
            setCurrentPage(data.page || 1);
        } catch (error) {
            console.error("Error fetching inventory:", error);
        } finally {
            setLoading(false);
        }
    }, [user, itemsPerPage, sessionTimeout, CRM_BASE]);

    const hasAdminAccess = user?.role === "company_admin" || user?.role === "company_owner";

    useEffect(() => {
        if (!isLoading && !hasAdminAccess) router.push("/");
    }, [user, isLoading, router, hasAdminAccess]);

    useEffect(() => {
        if (hasAdminAccess) fetchInventory(currentPage);
    }, [hasAdminAccess, fetchInventory, currentPage]);

    const set = (field: keyof Product) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
        setFormData(f => ({ ...f, [field]: e.target.value }));

    const handleOpenModal = (product?: Product) => {
        if (product) {
            setEditingProduct(product);
            setFormData({ ...EMPTY_FORM, ...product, price: product.price?.toString() ?? "" });
        } else {
            setEditingProduct(null);
            setFormData(EMPTY_FORM);
        }
        setIsModalOpen(true);
    };

    const handleDelete = async (id: number) => {
        if (!confirm("Delete this product?")) return;
        try {
            const res = await apiFetch(`${CRM_BASE}/inventory/${id}`, {
                method: "DELETE"
            });
            if (res.status === 401) { sessionTimeout(); return; }
            fetchInventory();
        } catch (error) {
            console.error("Error deleting product:", error);
        }
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            const url = editingProduct?.id ? `${CRM_BASE}/inventory/${editingProduct.id}` : `${CRM_BASE}/inventory`;
            const method = editingProduct?.id ? "PUT" : "POST";
            // strip empty strings → null so backend doesn't coerce to 0
            const payload: Record<string, unknown> = {};
            for (const [k, v] of Object.entries(formData)) {
                payload[k] = v === "" ? null : v;
            }
            const res = await apiFetch(url, {
                method,
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload) });
            if (res.status === 401) { sessionTimeout(); return; }
            if (res.ok) {
                setIsModalOpen(false);
                setEditingProduct(null);
                setFormData(EMPTY_FORM);
                fetchInventory();
            }
        } catch (error) {
            console.error("Error saving product:", error);
        }
    };

    const fmtPrice = (p?: string | number) => p != null && p !== "" ? `₹${Number(p).toLocaleString("en-IN")}` : "—";

    return (
        <div className="space-y-6 pb-8">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-4xl font-bold tracking-tight">
                        <span className="gradient-text">Inventory</span>
                    </h1>
                    <p className="mt-2 text-slate-600 dark:text-slate-400 font-medium">
                        Manage products, stock levels, and pricing for the Digital Sales Representative
                    </p>
                </div>
                <button
                    onClick={() => handleOpenModal()}
                    className="flex items-center space-x-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-6 py-3 font-semibold text-white shadow-lg shadow-violet-500/50 hover:shadow-xl hover:scale-105 transition-all duration-300"
                >
                    <Plus className="h-5 w-5" />
                    <span>Add Product</span>
                </button>
            </div>

            {/* Inventory Table */}
            <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
                <div className="overflow-x-auto">
                    <table className="w-full text-left">
                        <thead>
                            <tr className="border-b border-white/20 dark:border-white/10 bg-white/40 dark:bg-slate-800/40">
                                <th className="px-6 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">Product</th>
                                <th className="px-5 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">Brand / Line</th>
                                <th className="px-5 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">Category</th>
                                <th className="px-5 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">SKU</th>
                                <th className="px-5 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">Stock</th>
                                <th className="px-5 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">MRP</th>
                                <th className="px-5 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">Sell Price</th>
                                <th className="px-5 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">Status</th>
                                <th className="px-5 py-4 text-sm font-bold text-slate-700 dark:text-slate-300 text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-white/10 dark:divide-white/5">
                            {loading ? (
                                Array.from({ length: 5 }).map((_, i) => (
                                    <tr key={i} className="animate-pulse">
                                        {Array.from({ length: 9 }).map((__, j) => (
                                            <td key={j} className="px-5 py-4"><div className="h-4 bg-slate-200 dark:bg-slate-700 rounded-md" /></td>
                                        ))}
                                    </tr>
                                ))
                            ) : products.length === 0 ? (
                                <tr>
                                    <td colSpan={9} className="px-6 py-12 text-center text-slate-500">No products found in catalog.</td>
                                </tr>
                            ) : (
                                products.map((product) => (
                                    <tr key={product.id} className="hover:bg-white/40 dark:hover:bg-slate-800/40 transition-colors">
                                        <td className="px-6 py-4">
                                            <div className="flex items-center space-x-3">
                                                {product.image_url ? (
                                                    <img src={product.image_url} alt={product.name} className="h-10 w-10 rounded-lg object-cover" />
                                                ) : (
                                                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-violet-100 dark:bg-violet-900/30 flex-shrink-0">
                                                        <Package className="h-5 w-5 text-violet-600 dark:text-violet-400" />
                                                    </div>
                                                )}
                                                <div className="min-w-0">
                                                    <p className="font-bold text-slate-900 dark:text-slate-100 truncate max-w-[180px]">{product.name}</p>
                                                    {product.model_number && <p className="text-xs text-slate-500 truncate">{product.model_number}</p>}
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-5 py-4">
                                            {product.brand ? (
                                                <div>
                                                    <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">{product.brand}</p>
                                                    {product.product_line && <p className="text-xs text-slate-500">{product.product_line}</p>}
                                                </div>
                                            ) : <span className="text-slate-400 text-sm">—</span>}
                                        </td>
                                        <td className="px-5 py-4">
                                            {product.category ? (
                                                <div>
                                                    <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 dark:bg-blue-900/20 px-2.5 py-0.5 text-xs font-semibold text-blue-700 dark:text-blue-400">
                                                        <Layers className="h-3 w-3" />{product.category}
                                                    </span>
                                                    {product.subcategory && <p className="text-xs text-slate-500 mt-0.5">{product.subcategory}</p>}
                                                </div>
                                            ) : <span className="text-slate-400 text-sm">—</span>}
                                        </td>
                                        <td className="px-5 py-4 text-sm text-slate-600 dark:text-slate-400 font-mono">
                                            {product.sku || <span className="text-slate-400">—</span>}
                                        </td>
                                        <td className="px-5 py-4">
                                            <span className={`text-sm font-medium ${product.reorder_level && product.stock <= Number(product.reorder_level) ? "text-amber-600 dark:text-amber-400" : "text-slate-600 dark:text-slate-400"}`}>
                                                {product.stock} {product.unit || "units"}
                                            </span>
                                        </td>
                                        <td className="px-5 py-4 text-sm text-slate-500 line-through">{fmtPrice(product.mrp)}</td>
                                        <td className="px-5 py-4 text-violet-600 dark:text-violet-400 font-bold text-sm">{fmtPrice(product.price)}</td>
                                        <td className="px-5 py-4">
                                            <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-bold ${product.stock > 0
                                                ? "bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400 ring-1 ring-green-600/20"
                                                : "bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400 ring-1 ring-red-600/20"
                                            }`}>
                                                {product.stock > 0 ? "In Stock" : "Out of Stock"}
                                            </span>
                                        </td>
                                        <td className="px-5 py-4 text-right">
                                            <div className="flex justify-end space-x-2">
                                                <button
                                                    onClick={() => handleOpenModal(product)}
                                                    className="p-2 rounded-lg hover:bg-violet-100 dark:hover:bg-violet-900/30 text-violet-600 dark:text-violet-400 transition-colors"
                                                >
                                                    <Edit className="h-4 w-4" />
                                                </button>
                                                <button
                                                    onClick={() => product.id && handleDelete(product.id)}
                                                    className="p-2 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/30 text-red-600 dark:text-red-400 transition-colors"
                                                >
                                                    <Trash2 className="h-4 w-4" />
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
                {!loading && totalProducts > 0 && (
                    <div className="px-6 py-4 border-t border-white/20 dark:border-white/10 bg-white/40 dark:bg-slate-800/40">
                        <Pagination
                            currentPage={currentPage}
                            totalPages={totalPages}
                            onPageChange={(page) => setCurrentPage(page)}
                            totalItems={totalProducts}
                            itemsPerPage={itemsPerPage}
                        />
                    </div>
                )}
            </div>

            {/* Add / Edit Modal */}
            {isModalOpen && (
                <div className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-10 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-300 overflow-y-auto">
                    <div className="w-full max-w-2xl rounded-3xl glass p-8 border border-white/20 dark:border-white/10 shadow-2xl relative mb-10">
                        <div className="absolute -top-24 -right-24 h-48 w-48 rounded-full bg-violet-600/20 blur-3xl pointer-events-none" />
                        <div className="absolute -bottom-24 -left-24 h-48 w-48 rounded-full bg-blue-600/20 blur-3xl pointer-events-none" />

                        <div className="relative">
                            <div className="flex items-center justify-between mb-6">
                                <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100 italic">
                                    {editingProduct ? "Edit Product" : "Add New Product"}
                                </h2>
                                <button onClick={() => setIsModalOpen(false)} className="p-2 text-slate-400 hover:text-slate-600 transition-colors">
                                    <X className="h-6 w-6" />
                                </button>
                            </div>

                            <form onSubmit={handleSubmit} className="space-y-4">

                                {/* Basic Info */}
                                <FieldGroup title="Basic Info">
                                    <div className="space-y-1.5">
                                        <label className={labelCls}>Product Name *</label>
                                        <input type="text" required value={formData.name} onChange={set("name")} className={inputCls} placeholder="e.g. Samsung 75″ Neo QLED 8K" />
                                    </div>
                                    <div className="grid grid-cols-2 gap-3">
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>SKU</label>
                                            <input type="text" value={formData.sku ?? ""} onChange={set("sku")} className={inputCls} placeholder="QN75QN900D" />
                                        </div>
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>Model Number</label>
                                            <input type="text" value={formData.model_number ?? ""} onChange={set("model_number")} className={inputCls} placeholder="QN900D" />
                                        </div>
                                    </div>
                                    <div className="space-y-1.5">
                                        <label className={labelCls}>Description</label>
                                        <textarea value={formData.description ?? ""} onChange={set("description")} rows={2}
                                            className={inputCls + " resize-none"} placeholder="Key features, specs summary…" />
                                    </div>
                                    <div className="space-y-1.5">
                                        <label className={labelCls}>Notes (internal)</label>
                                        <textarea value={formData.note ?? ""} onChange={set("note")} rows={2}
                                            className={inputCls + " resize-none"} placeholder="Special handling, installation details…" />
                                    </div>
                                </FieldGroup>

                                {/* Brand & Classification */}
                                <FieldGroup title="Brand & Classification">
                                    <div className="grid grid-cols-2 gap-3">
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>Brand / Manufacturer</label>
                                            <input type="text" value={formData.brand ?? ""} onChange={set("brand")} className={inputCls} placeholder="Samsung" />
                                        </div>
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>Product Line / Series</label>
                                            <input type="text" value={formData.product_line ?? ""} onChange={set("product_line")} className={inputCls} placeholder="Neo QLED 8K" />
                                        </div>
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>Category</label>
                                            <input type="text" value={formData.category ?? ""} onChange={set("category")} className={inputCls} placeholder="Television" />
                                        </div>
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>Sub-category</label>
                                            <input type="text" value={formData.subcategory ?? ""} onChange={set("subcategory")} className={inputCls} placeholder="8K QLED" />
                                        </div>
                                    </div>
                                </FieldGroup>

                                {/* Pricing */}
                                <FieldGroup title="Pricing">
                                    <div className="grid grid-cols-3 gap-3">
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>MRP</label>
                                            <input type="number" min="0" step="0.01" value={formData.mrp ?? ""} onChange={set("mrp")} className={inputCls} placeholder="0.00" />
                                        </div>
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>Selling Price *</label>
                                            <input type="number" required min="0" step="0.01" value={formData.price} onChange={set("price")} className={inputCls} placeholder="0.00" />
                                        </div>
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>Cost Price</label>
                                            <input type="number" min="0" step="0.01" value={formData.cost_price ?? ""} onChange={set("cost_price")} className={inputCls} placeholder="0.00" />
                                        </div>
                                    </div>
                                    <div className="grid grid-cols-2 gap-3">
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>Min Price (floor)</label>
                                            <input type="number" min="0" step="0.01" value={formData.min_price ?? ""} onChange={set("min_price")} className={inputCls} placeholder="0.00" />
                                        </div>
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>Currency</label>
                                            <select value={formData.currency ?? "INR"} onChange={set("currency")} className={inputCls}>
                                                <option>INR</option>
                                                <option>USD</option>
                                                <option>EUR</option>
                                                <option>GBP</option>
                                                <option>AED</option>
                                            </select>
                                        </div>
                                    </div>
                                </FieldGroup>

                                {/* Tax & Compliance */}
                                <FieldGroup title="Tax & Compliance">
                                    <div className="grid grid-cols-3 gap-3">
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>HSN Code</label>
                                            <input type="text" value={formData.hsn_code ?? ""} onChange={set("hsn_code")} className={inputCls} placeholder="8528" />
                                        </div>
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>GST Rate (%)</label>
                                            <input type="number" min="0" max="100" step="0.01" value={formData.tax_rate ?? ""} onChange={set("tax_rate")} className={inputCls} placeholder="18" />
                                        </div>
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>Unit</label>
                                            <input type="text" value={formData.unit ?? ""} onChange={set("unit")} className={inputCls} placeholder="piece / box / set" />
                                        </div>
                                    </div>
                                </FieldGroup>

                                {/* Stock & Logistics */}
                                <FieldGroup title="Stock & Logistics">
                                    <div className="grid grid-cols-3 gap-3">
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>Stock Qty *</label>
                                            <input type="number" required min="0" value={formData.stock}
                                                onChange={(e) => setFormData(f => ({ ...f, stock: parseInt(e.target.value, 10) || 0 }))}
                                                className={inputCls} />
                                        </div>
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>Reorder Level</label>
                                            <input type="number" min="0" value={formData.reorder_level ?? ""} onChange={set("reorder_level")} className={inputCls} placeholder="5" />
                                        </div>
                                        <div className="space-y-1.5">
                                            <label className={labelCls}>Warranty (months)</label>
                                            <input type="number" min="0" value={formData.warranty_months ?? ""} onChange={set("warranty_months")} className={inputCls} placeholder="12" />
                                        </div>
                                    </div>
                                </FieldGroup>

                                {/* Media */}
                                <FieldGroup title="Media">
                                    <div className="space-y-1.5">
                                        <label className={labelCls}>Image URL</label>
                                        <input type="url" value={formData.image_url ?? ""} onChange={set("image_url")} className={inputCls} placeholder="https://…" />
                                    </div>
                                    {formData.image_url && (
                                        <img src={formData.image_url} alt="preview" className="h-24 rounded-xl object-contain bg-slate-100 dark:bg-slate-800 p-2" />
                                    )}
                                </FieldGroup>

                                <div className="flex space-x-3 pt-2">
                                    <button type="button" onClick={() => setIsModalOpen(false)}
                                        className="flex-1 rounded-xl border border-slate-200 dark:border-slate-700 p-3 font-bold text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">
                                        Cancel
                                    </button>
                                    <button type="submit"
                                        className="flex-1 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 p-3 font-bold text-white shadow-lg shadow-violet-500/50 hover:shadow-xl transition-all">
                                        {editingProduct ? "Save Changes" : "Add Product"}
                                    </button>
                                </div>
                            </form>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
