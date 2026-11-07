import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/** Inline a vendored SVG so its elements can be styled by id and hovered.
 *
 * Only our own files under public/gene are ever passed here; they are static assets that
 * ship with the app, not remote content.
 */
export function InlineSvg({
  svg,
  className,
  ...rest
}: { svg: string } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("[&>svg]:block [&>svg]:h-auto [&>svg]:w-full", className)}
      // biome-ignore lint/security/noDangerouslySetInnerHtml: static asset bundled with the app
      dangerouslySetInnerHTML={{ __html: svg }}
      {...rest}
    />
  );
}
