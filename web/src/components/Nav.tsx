"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [["/", "Overview"], ["/call", "The call"], ["/runs", "Runs"], ["/eval", "Reliability"], ["/gate", "Gate & policy"]] as const;

export default function Nav() {
  const p = usePathname();
  return (
    <nav className="top">
      <Link href="/" className="brand">Rebuttal</Link>
      {links.map(([href, label]) => (
        <Link key={href} href={href} className="link" aria-current={p === href ? "page" : undefined}>{label}</Link>
      ))}
      <span className="spacer" />
      <a className="link" href="https://github.com/N-45div/Rebuttal">GitHub</a>
    </nav>
  );
}
