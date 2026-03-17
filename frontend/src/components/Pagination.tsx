"use client";

import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";

interface PaginationProps {
    currentPage: number;
    totalPages: number;
    onPageChange: (page: number) => void;
    totalItems: number;
    itemsPerPage: number;
}

export default function Pagination({
    currentPage,
    totalPages,
    onPageChange,
    totalItems,
    itemsPerPage
}: PaginationProps) {
    if (totalPages <= 1) return null;

    const startItem = (currentPage - 1) * itemsPerPage + 1;
    const endItem = Math.min(currentPage * itemsPerPage, totalItems);

    const getPageNumbers = () => {
        const pages = [];
        const delta = 2; // Number of pages to show before and after current page

        for (let i = 1; i <= totalPages; i++) {
            if (
                i === 1 ||
                i === totalPages ||
                (i >= currentPage - delta && i <= currentPage + delta)
            ) {
                pages.push(i);
            } else if (
                (i === currentPage - delta - 1 && i > 1) ||
                (i === currentPage + delta + 1 && i < totalPages)
            ) {
                pages.push('...');
            }
        }
        return [...new Set(pages)]; // Remove duplicates just in case
    };

    return (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 mt-6 px-2">
            <div className="text-sm font-medium text-slate-500 dark:text-slate-400">
                Showing <span className="text-slate-900 dark:text-white font-bold">{startItem}</span> to <span className="text-slate-900 dark:text-white font-bold">{endItem}</span> of <span className="text-slate-900 dark:text-white font-bold">{totalItems}</span> entries
            </div>

            <div className="flex items-center space-x-1">
                <button
                    onClick={() => onPageChange(1)}
                    disabled={currentPage === 1}
                    className="p-2 rounded-lg glass border border-white/10 hover:bg-white/10 dark:hover:bg-white/5 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                    title="First Page"
                >
                    <ChevronsLeft className="h-4 w-4" />
                </button>
                <button
                    onClick={() => onPageChange(currentPage - 1)}
                    disabled={currentPage === 1}
                    className="p-2 rounded-lg glass border border-white/10 hover:bg-white/10 dark:hover:bg-white/5 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                    title="Previous Page"
                >
                    <ChevronLeft className="h-4 w-4" />
                </button>

                <div className="flex items-center space-x-1 px-2">
                    {getPageNumbers().map((page, index) => (
                        page === '...' ? (
                            <span key={`ellipsis-${index}`} className="px-2 text-slate-400">...</span>
                        ) : (
                            <button
                                key={`page-${page}`}
                                onClick={() => onPageChange(Number(page))}
                                className={`min-w-[36px] h-9 rounded-lg font-bold text-sm transition-all duration-300 ${
                                    currentPage === page
                                        ? "bg-gradient-to-r from-violet-600 to-blue-600 text-white shadow-lg shadow-violet-500/30 scale-110"
                                        : "hover:bg-white/10 dark:hover:bg-white/5 text-slate-600 dark:text-slate-400"
                                }`}
                            >
                                {page}
                            </button>
                        )
                    ))}
                </div>

                <button
                    onClick={() => onPageChange(currentPage + 1)}
                    disabled={currentPage === totalPages}
                    className="p-2 rounded-lg glass border border-white/10 hover:bg-white/10 dark:hover:bg-white/5 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                    title="Next Page"
                >
                    <ChevronRight className="h-4 w-4" />
                </button>
                <button
                    onClick={() => onPageChange(totalPages)}
                    disabled={currentPage === totalPages}
                    className="p-2 rounded-lg glass border border-white/10 hover:bg-white/10 dark:hover:bg-white/5 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                    title="Last Page"
                >
                    <ChevronsRight className="h-4 w-4" />
                </button>
            </div>
        </div>
    );
}
