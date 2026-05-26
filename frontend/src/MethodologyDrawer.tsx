import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { X } from "lucide-react";

interface MethodologySection {
  title: string;
  slug: string;
  summary: string;
  body: string;
  hasExample: boolean;
}

function parseMethodologySections(markdown: string): MethodologySection[] {
  return markdown
    .split(/\n---\n/)
    .filter((s) => s.trim())
    .map((section) => {
      const headingMatch = section.match(/^#+\s+(.+)/m);
      const title = headingMatch?.[1] ?? "Overview";
      const slug = title
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/(^-|-$)/g, "");
      const afterHeading = section.replace(/^#+\s+.+\n?/, "").trim();
      const paragraphs = afterHeading.split(/\n\n/);
      const summary = paragraphs[0]?.replace(/^>\s*/gm, "").trim() ?? "";
      const hasExample = /worked example/i.test(section);
      return { title, slug, summary, body: section, hasExample };
    });
}

export function MethodologyDrawer({
  markdown,
  isOpen,
  initialSection,
  onClose,
}: {
  markdown: string;
  isOpen: boolean;
  initialSection: string | null;
  onClose: () => void;
}) {
  const sections = parseMethodologySections(markdown);
  const [activeSlug, setActiveSlug] = useState<string | null>(null);
  const [expandedSlugs, setExpandedSlugs] = useState<Set<string>>(new Set());
  const bodyRef = useRef<HTMLDivElement>(null);
  const sectionRefs = useRef<Map<string, HTMLElement>>(new Map());

  const toggleSection = useCallback((slug: string) => {
    setExpandedSlugs((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) {
        next.delete(slug);
      } else {
        next.add(slug);
      }
      return next;
    });
  }, []);

  useEffect(() => {
    if (!isOpen || !initialSection) return;
    const match = sections.find((s) => s.slug.includes(initialSection));
    if (!match) return;

    setExpandedSlugs((prev) => new Set([...prev, match.slug]));

    requestAnimationFrame(() => {
      const el = sectionRefs.current.get(match.slug);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }, [isOpen, initialSection, sections]);

  useEffect(() => {
    if (!isOpen) return;
    const body = bodyRef.current;
    if (!body) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const slug = entry.target.getAttribute("data-slug");
            if (slug) setActiveSlug(slug);
          }
        }
      },
      { root: body, rootMargin: "-20% 0px -70% 0px", threshold: 0 }
    );

    for (const el of sectionRefs.current.values()) {
      observer.observe(el);
    }

    return () => observer.disconnect();
  }, [isOpen, sections]);

  const scrollToSection = useCallback(
    (slug: string) => {
      setExpandedSlugs((prev) => new Set([...prev, slug]));
      requestAnimationFrame(() => {
        const el = sectionRefs.current.get(slug);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
    },
    []
  );

  if (!isOpen) return null;

  return (
    <div className="drawer-backdrop" onClick={onClose} role="presentation">
      <aside
        className="drawer-panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Methodology"
      >
        <header className="drawer-header">
          <h2>Methodology</h2>
          <button className="drawer-close" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>

        <nav className="drawer-nav">
          {sections.map((section) => (
            <button
              key={section.slug}
              className={activeSlug === section.slug ? "active" : ""}
              onClick={() => scrollToSection(section.slug)}
            >
              {section.title.length > 24
                ? section.title.slice(0, 22) + "..."
                : section.title}
            </button>
          ))}
        </nav>

        <div className="drawer-body" ref={bodyRef}>
          {sections.map((section) => {
            const isExpanded = expandedSlugs.has(section.slug);
            return (
              <div
                key={section.slug}
                className={`methodology-section${section.hasExample ? " methodology-example" : ""}`}
                data-slug={section.slug}
                ref={(el) => {
                  if (el) sectionRefs.current.set(section.slug, el);
                }}
              >
                <button
                  className="section-toggle"
                  onClick={() => toggleSection(section.slug)}
                  aria-expanded={isExpanded}
                >
                  <span className="toggle-icon">{isExpanded ? "−" : "+"}</span>
                  <span className="section-title">{section.title}</span>
                </button>

                {!isExpanded && section.summary ? (
                  <p className="section-summary">{section.summary}</p>
                ) : null}

                {isExpanded ? (
                  <div className="section-content">
                    <ReactMarkdown>{section.body}</ReactMarkdown>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </aside>
    </div>
  );
}
