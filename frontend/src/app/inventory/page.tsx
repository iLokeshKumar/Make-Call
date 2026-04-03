"use client";

import { useEffect, useState, useCallback } from "react";
import { Package, Plus, Trash2, Edit, AlertCircle, Save, X } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useRouter } from "next/navigation";
import Pagination from "@/components/Pagination";

interface Product {
    id?: number;
    name: string;
    stock: number;
    price: string;
    note?: string;
}

export default function InventoryPage() {
    const { user, token, isLoading, sessionTimeout } = useAuth();
    const router = useRouter();
    const [products, setProducts] = useState<Product[]>([]);
    const [loading, setLoading] = useState(true);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingProduct, setEditingProduct] = useState<Product | null>(null);
    const [formData, setFormData] = useState<Product>({ name: "", stock: 0, price: "" });

    // Pagination State
    const [currentPage, setCurrentPage] = useState(1);
    const [totalProducts, setTotalProducts] = useState(0);
    const [itemsPerPage] = useState(10);
    const totalPages = Math.ceil(totalProducts / itemsPerPage);

    const API_BASE = "http://localhost:6060";
    const CRM_BASE = `${API_BASE}/crm`;

    const fetchInventory = useCallback(async (page: number = 1) => {
        setLoading(true);
        try {
            const res = await fetch(`${CRM_BASE}/inventory?page=${page}&limit=${itemsPerPage}`, {
                headers: { "Authorization": `Bearer ${token}` }
            });
            if (res.status === 401) {
                sessionTimeout();
                return;
            }
            const data = await res.json();
            setProducts(data.items || []);
            setTotalProducts(data.total || 0);
            setCurrentPage(data.page || 1);
        } catch (error) {
            console.error("Error fetching inventory:", error);
        } finally {
            setLoading(false);
        }
    }, [token, itemsPerPage, sessionTimeout]);

    const hasAdminAccess = user?.role === "company_admin" || user?.role === "company_owner";

    useEffect(() => {
        if (!isLoading && !hasAdminAccess) {
            router.push("/");
        }
    }, [user, isLoading, router]);

    useEffect(() => {
        if (hasAdminAccess) {
            fetchInventory(currentPage);
        }
    }, [hasAdminAccess, fetchInventory, currentPage]);

    const handleOpenModal = (product?: Product) => {
        if (product) {
            setEditingProduct(product);
            setFormData({
                ...product,
                price: product.price?.toString() ?? "",
            });
        } else {
            setEditingProduct(null);
            setFormData({ name: "", stock: 0, price: "" });
        }
        setIsModalOpen(true);
    };

    const handleDelete = async (id: number) => {
        if (!confirm("Are you sure you want to delete this product?")) return;
        try {
            const res = await fetch(`${CRM_BASE}/inventory/${id}`, {
                method: "DELETE",
                headers: { "Authorization": `Bearer ${token}` }
            });
            if (res.status === 401) {
                sessionTimeout();
                return;
            }
            fetchInventory();
        } catch (error) {
            console.error("Error deleting product:", error);
        }
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            const url = editingProduct && editingProduct.id ? `${CRM_BASE}/inventory/${editingProduct.id}` : `${CRM_BASE}/inventory`;
            const method = editingProduct && editingProduct.id ? "PUT" : "POST";
            const res = await fetch(url, {
                method,
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": `Bearer ${token}`
                },
                body: JSON.stringify(formData),
            });
            if (res.status === 401) {
                sessionTimeout();
                return;
            }
            if (res.ok) {
                setIsModalOpen(false);
                setEditingProduct(null);
                setFormData({ name: "", stock: 0, price: "" });
                fetchInventory();
            }
        } catch (error) {
            console.error("Error saving product:", error);
        }
    };

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
                                <th className="px-6 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">Product Name</th>
                                <th className="px-6 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">Stock</th>
                                <th className="px-6 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">Price</th>
                                <th className="px-6 py-4 text-sm font-bold text-slate-700 dark:text-slate-300">Status</th>
                                <th className="px-6 py-4 text-sm font-bold text-slate-700 dark:text-slate-300 text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-white/10 dark:divide-white/5">
                            {loading ? (
                                Array.from({ length: 5 }).map((_, i) => (
                                    <tr key={i} className="animate-pulse">
                                        <td className="px-6 py-4"><div className="h-6 w-32 bg-slate-200 dark:bg-slate-700 rounded-md" /></td>
                                        <td className="px-6 py-4"><div className="h-4 w-16 bg-slate-200 dark:bg-slate-700 rounded-md" /></td>
                                        <td className="px-6 py-4"><div className="h-4 w-12 bg-slate-200 dark:bg-slate-700 rounded-md" /></td>
                                        <td className="px-6 py-4"><div className="h-6 w-16 bg-slate-200 dark:bg-slate-700 rounded-full" /></td>
                                        <td className="px-6 py-4 text-right"><div className="h-8 w-16 ml-auto bg-slate-200 dark:bg-slate-700 rounded-lg" /></td>
                                    </tr>
                                ))
                            ) : products.length === 0 ? (
                                <tr>
                                    <td colSpan={5} className="px-6 py-12 text-center text-slate-500">No products found in catalog.</td>
                                </tr>
                            ) : (
                                products.map((product) => (
                                    <tr key={product.id} className="hover:bg-white/40 dark:hover:bg-slate-800/40 transition-colors">
                                        <td className="px-6 py-4">
                                            <div className="flex items-center space-x-3">
                                                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-violet-100 dark:bg-violet-900/30">
                                                    <Package className="h-5 w-5 text-violet-600 dark:text-violet-400" />
                                                </div>
                                                <div>
                                                    <p className="font-bold text-slate-900 dark:text-slate-100">{product.name}</p>
                                                    {product.note && <p className="text-xs text-slate-500">{product.note}</p>}
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 text-slate-600 dark:text-slate-400 font-medium">
                                            {product.stock} units
                                        </td>
                                        <td className="px-6 py-4 text-violet-600 dark:text-violet-400 font-bold">
                                            {product.price}
                                        </td>
                                        <td className="px-6 py-4">
                                            <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-bold ${product.stock > 0
                                                ? 'bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400 ring-1 ring-green-600/20'
                                                : 'bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400 ring-1 ring-red-600/20'
                                                }`}>
                                                {product.stock > 0 ? "In Stock" : "Out of Stock"}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 text-right">
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

            {/* Modal */}
            {isModalOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-300">
                    <div className="w-full max-w-lg rounded-3xl glass p-8 border border-white/20 dark:border-white/10 shadow-2xl scale-in-center overflow-hidden relative">
                        {/* Background Blobs */}
                        <div className="absolute -top-24 -right-24 h-48 w-48 rounded-full bg-violet-600/20 blur-3xl" />
                        <div className="absolute -bottom-24 -left-24 h-48 w-48 rounded-full bg-blue-600/20 blur-3xl" />

                        <div className="relative">
                            <div className="flex items-center justify-between mb-8">
                                <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100 italic">
                                    {editingProduct ? "Edit Product" : "Add New Product"}
                                </h2>
                                <button onClick={() => setIsModalOpen(false)} className="p-2 text-slate-400 hover:text-slate-600 transition-colors">
                                    <X className="h-6 w-6" />
                                </button>
                            </div>

                            <form onSubmit={handleSubmit} className="space-y-6">
                                <div className="space-y-4">
                                    <div className="space-y-1.5">
                                        <label className="text-sm font-bold text-slate-700 dark:text-slate-300 ml-1">Product Name</label>
                                        <input
                                            type="text"
                                            required
                                            value={formData.name}
                                            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                            className="w-full rounded-xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-800/60 backdrop-blur-sm p-3 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-violet-400 shadow-sm"
                                            placeholder="e.g. Samsung 75' QLED TV"
                                        />
                                    </div>
                                    <div className="grid grid-cols-2 gap-4">
                                        <div className="space-y-1.5">
                                            <label className="text-sm font-bold text-slate-700 dark:text-slate-300 ml-1">Stock Quantity</label>
                                            <input
                                                type="number"
                                                required
                                                value={formData.stock}
                                                onChange={(e) => {
                                                    const parsed = parseInt(e.target.value, 10);
                                                    setFormData({
                                                        ...formData,
                                                        stock: Number.isNaN(parsed) ? 0 : parsed,
                                                    });
                                                }}
                                                className="w-full rounded-xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-800/60 backdrop-blur-sm p-3 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-violet-400 shadow-sm"
                                            />
                                        </div>
                                        <div className="space-y-1.5">
                                            <label className="text-sm font-bold text-slate-700 dark:text-slate-300 ml-1">Price</label>
                                            <input
                                                type="text"
                                                required
                                                value={formData.price}
                                                onChange={(e) => setFormData({ ...formData, price: e.target.value })}
                                                className="w-full rounded-xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-800/60 backdrop-blur-sm p-3 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-violet-400 shadow-sm"
                                                placeholder="e.g. ₹1,20,000"
                                            />
                                        </div>
                                    </div>
                                    <div className="space-y-1.5">
                                        <label className="text-sm font-bold text-slate-700 dark:text-slate-300 ml-1">Notes (Optional)</label>
                                        <textarea
                                            value={formData.note || ""}
                                            onChange={(e) => setFormData({ ...formData, note: e.target.value })}
                                            className="w-full rounded-xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-800/60 backdrop-blur-sm p-3 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-violet-400 shadow-sm min-h-[100px]"
                                            placeholder="Special handling or installation details..."
                                        />
                                    </div>
                                </div>

                                <div className="flex space-x-3 pt-4">
                                    <button
                                        type="button"
                                        onClick={() => setIsModalOpen(false)}
                                        className="flex-1 rounded-xl border border-slate-200 dark:border-slate-700 p-3 font-bold text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
                                    >
                                        Cancel
                                    </button>
                                    <button
                                        type="submit"
                                        className="flex-1 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 p-3 font-bold text-white shadow-lg shadow-violet-500/50 hover:shadow-xl transition-all"
                                    >
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
