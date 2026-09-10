import React from "react";

interface DiffViewerProps {
  sourceContent: string;
  translatedContent: string | null;
}

export const DiffViewer: React.FC<DiffViewerProps> = ({ sourceContent, translatedContent }) => {
  let sourceObj: Record<string, any> = {};
  let translatedObj: Record<string, any> = {};

  try {
    sourceObj = jsonParseOrEmpty(sourceContent);
    translatedObj = jsonParseOrEmpty(translatedContent || "{}");
  } catch (e) {
    // Parsing error fallback
  }

  function jsonParseOrEmpty(str: string): Record<string, any> {
    try {
      return JSON.parse(str);
    } catch {
      return {};
    }
  }

  // 중괄호 변수를 형광펜처럼 하이라이팅하기 위한 헬퍼 함수
  const highlightVariables = (text: string) => {
    if (typeof text !== "string") return text;
    const parts = text.split(/(\{.*?\})/);
    return parts.map((part, index) => {
      if (part.startsWith("{") && part.endsWith("}")) {
        return (
          <span
            key={index}
            style={{
              backgroundColor: "rgba(139, 92, 246, 0.3)",
              color: "#c084fc",
              padding: "2px 4px",
              borderRadius: "4px",
              fontWeight: "bold",
              fontFamily: "monospace"
            }}
          >
            {part}
          </span>
        );
      }
      return part;
    });
  };

  const flatten = (value: any, prefix = ""): Record<string, any> => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return { [prefix]: value };
    return Object.entries(value).reduce<Record<string, any>>((result, [key, child]) => {
      const path = prefix ? `${prefix}.${key}` : key;
      return { ...result, ...flatten(child, path) };
    }, {});
  };

  const sourceFlat = flatten(sourceObj);
  const translatedFlat = flatten(translatedObj);
  const allKeys = Array.from(new Set([...Object.keys(sourceFlat), ...Object.keys(translatedFlat)]));

  return (
    <div style={{ marginTop: "1rem" }}>
      {allKeys.length === 0 ? (
        <div style={{ color: "var(--text-muted)", fontSize: "0.9rem", textAlign: "center", padding: "2rem" }}>
          표시할 번역 데이터가 없습니다.
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table className="diff-table">
            <thead>
              <tr style={{ borderBottom: "2px solid var(--border)", textAlign: "left" }}>
                <th style={{ padding: "0.5rem", color: "var(--text-muted)" }}>Key</th>
                <th style={{ padding: "0.5rem", color: "var(--error)" }}>Source (ko-KR)</th>
                <th style={{ padding: "0.5rem", color: "var(--success)" }}>Translation</th>
              </tr>
            </thead>
            <tbody>
              {allKeys.map((key) => {
                const srcExists = Object.prototype.hasOwnProperty.call(sourceFlat, key);
                const tgtExists = Object.prototype.hasOwnProperty.call(translatedFlat, key);
                const srcVal = srcExists ? sourceFlat[key] : <span style={{ color: "var(--error)", fontStyle: "italic" }}>[삭제됨]</span>;
                const tgtVal = tgtExists ? translatedFlat[key] : <span style={{ color: "var(--error)", fontStyle: "italic" }}>[누락됨]</span>;

                return (
                  <tr key={key} className="diff-row">
                    <td className="diff-cell key">{key}</td>
                    <td className="diff-cell src">{typeof srcVal === "string" ? highlightVariables(srcVal) : JSON.stringify(srcVal)}</td>
                    <td className="diff-cell tgt">{typeof tgtVal === "string" ? highlightVariables(tgtVal) : JSON.stringify(tgtVal)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
