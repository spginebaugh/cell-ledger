import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 rounded-md border font-semibold transition-colors disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap select-none",
  {
    variants: {
      variant: {
        primary: "bg-accent text-bg border-accent hover:opacity-90",
        secondary: "bg-surface text-ink border-line-2 hover:border-accent hover:text-accent-ink",
        ghost: "bg-transparent text-ink-2 border-transparent hover:border-line-2 hover:text-ink",
        danger: "bg-danger-soft text-danger border-danger/40 hover:opacity-90",
        accent: "bg-accent text-bg border-accent hover:opacity-90",
      },
      size: {
        sm: "h-8 px-2.5 text-[12px]",
        md: "h-9 px-3.5 text-[13px]",
        lg: "h-11 px-5 text-[14px]",
        icon: "h-9 w-9 p-0",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants>;

export function Button({ className, variant, size, type = "button", ...props }: ButtonProps) {
  return (
    <button type={type} className={cn(buttonVariants({ variant, size }), className)} {...props} />
  );
}
