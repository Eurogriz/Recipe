import * as React from "react";
import { cn } from "@/lib/utils";

export function Table({ className, ...rest }: React.HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-auto rounded-lg border border-border">
      <table className={cn("w-full caption-bottom text-sm", className)} {...rest} />
    </div>
  );
}

export const THead = (p: React.HTMLAttributes<HTMLTableSectionElement>) => (
  <thead className={cn("bg-muted/60 [&_tr]:border-b", p.className)} {...p} />
);

export const TBody = (p: React.HTMLAttributes<HTMLTableSectionElement>) => (
  <tbody className={cn("[&_tr:last-child]:border-0", p.className)} {...p} />
);

export const TR = (p: React.HTMLAttributes<HTMLTableRowElement>) => (
  <tr
    className={cn(
      "border-b border-border transition-colors hover:bg-muted/40 data-[state=selected]:bg-muted",
      p.className
    )}
    {...p}
  />
);

export const TH = (p: React.ThHTMLAttributes<HTMLTableCellElement>) => (
  <th
    className={cn(
      "h-10 px-3 text-left align-middle font-medium text-muted-foreground text-xs uppercase tracking-wide [&:has([role=checkbox])]:pr-0",
      p.className
    )}
    {...p}
  />
);

export const TD = (p: React.TdHTMLAttributes<HTMLTableCellElement>) => (
  <td className={cn("p-3 align-middle", p.className)} {...p} />
);
