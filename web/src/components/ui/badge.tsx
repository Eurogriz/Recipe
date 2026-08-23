import * as React from "react";
import { cn } from "@/lib/utils";

type Variant = "default" | "outline" | "success" | "warning" | "destructive" | "info";

const styles: Record<Variant, string> = {
  default: "bg-secondary text-secondary-foreground",
  outline: "border border-border text-foreground bg-transparent",
  success: "bg-green-100 text-green-900 border border-green-200",
  warning: "bg-amber-100 text-amber-900 border border-amber-200",
  destructive: "bg-red-100 text-red-900 border border-red-200",
  info: "bg-blue-100 text-blue-900 border border-blue-200",
};

export function Badge({
  variant = "default",
  className,
  ...rest
}: React.HTMLAttributes<HTMLSpanElement> & { variant?: Variant }) {
  return (
    <span
      {...rest}
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        styles[variant],
        className
      )}
    />
  );
}
