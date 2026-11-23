// Rich text editor (TipTap, MIT). textarea[data-rich] larni vizual editorga aylantiradi.
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import Image from "@tiptap/extension-image";
import { Table, TableRow, TableCell, TableHeader } from "@tiptap/extension-table";
import TextAlign from "@tiptap/extension-text-align";
import Placeholder from "@tiptap/extension-placeholder";
import Highlight from "@tiptap/extension-highlight";
import Youtube from "@tiptap/extension-youtube";
import CodeBlockLowlight from "@tiptap/extension-code-block-lowlight";
import { createLowlight } from "lowlight";
import python from "highlight.js/lib/languages/python";
import javascript from "highlight.js/lib/languages/javascript";
import typescript from "highlight.js/lib/languages/typescript";
import java from "highlight.js/lib/languages/java";
import cpp from "highlight.js/lib/languages/cpp";
import c from "highlight.js/lib/languages/c";
import csharp from "highlight.js/lib/languages/csharp";
import go from "highlight.js/lib/languages/go";
import rust from "highlight.js/lib/languages/rust";
import php from "highlight.js/lib/languages/php";
import kotlin from "highlight.js/lib/languages/kotlin";
import swift from "highlight.js/lib/languages/swift";
import sql from "highlight.js/lib/languages/sql";
import xml from "highlight.js/lib/languages/xml";
import css from "highlight.js/lib/languages/css";
import json from "highlight.js/lib/languages/json";
import bash from "highlight.js/lib/languages/bash";

const lowlight = createLowlight({ python, javascript, typescript, java, cpp, c, csharp, go, rust, php, kotlin, swift, sql, xml, css, json, bash });
const LANGS = [
  ["", "Til"], ["python", "Python"], ["javascript", "JavaScript"], ["typescript", "TypeScript"], ["java", "Java"],
  ["cpp", "C++"], ["c", "C"], ["csharp", "C#"], ["go", "Go"], ["rust", "Rust"], ["php", "PHP"], ["kotlin", "Kotlin"],
  ["swift", "Swift"], ["sql", "SQL"], ["xml", "HTML/XML"], ["css", "CSS"], ["json", "JSON"], ["bash", "Bash"],
];

function cookie(name) {
  const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
  return m ? decodeURIComponent(m[1]) : "";
}

async function uploadImage(file, url) {
  const fd = new FormData();
  fd.append("image", file);
  const res = await fetch(url, { method: "POST", body: fd, headers: { "X-CSRFToken": cookie("csrftoken") }, credentials: "same-origin" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Yuklashda xato");
  return (await res.json()).url;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text) e.textContent = text;
  return e;
}

function build(textarea) {
  if (textarea.dataset.rteReady) return;
  textarea.dataset.rteReady = "1";
  const uploadUrl = textarea.dataset.uploadUrl || "/yuklash/rasm/";
  const wrap = el("div", "rte");
  const toolbar = el("div", "rte-toolbar");
  const host = el("div", "rte-host");
  wrap.append(toolbar, host);
  textarea.parentNode.insertBefore(wrap, textarea);
  textarea.style.display = "none";

  const insertImageFile = async (editor, file) => {
    try {
      const url = await uploadImage(file, uploadUrl);
      editor.chain().focus().setImage({ src: url, alt: file.name }).run();
    } catch (e) { alert(e.message); }
  };

  const editor = new Editor({
    element: host,
    content: textarea.value || "",
    extensions: [
      StarterKit.configure({ codeBlock: false, heading: { levels: [2, 3, 4] }, link: { openOnClick: false, autolink: true } }),
      CodeBlockLowlight.configure({ lowlight }),
      Image.configure({ inline: false }),
      Table.configure({ resizable: false }), TableRow, TableHeader, TableCell,
      TextAlign.configure({ types: ["heading", "paragraph"] }),
      Highlight,
      Youtube.configure({ width: 640, height: 360, nocookie: true }),
      Placeholder.configure({ placeholder: textarea.getAttribute("placeholder") || "Matn yozing…" }),
    ],
    editorProps: {
      attributes: { class: "rte-content" },
      handlePaste(view, event) {
        const files = [...(event.clipboardData?.files || [])].filter((f) => f.type.startsWith("image/"));
        if (!files.length) return false;
        files.forEach((f) => insertImageFile(editor, f));
        return true;
      },
      handleDrop(view, event) {
        const files = [...(event.dataTransfer?.files || [])].filter((f) => f.type.startsWith("image/"));
        if (!files.length) return false;
        event.preventDefault();
        files.forEach((f) => insertImageFile(editor, f));
        return true;
      },
    },
    onUpdate: ({ editor }) => { textarea.value = editor.isEmpty ? "" : editor.getHTML(); },
  });

  const c = () => editor.chain().focus();
  const items = [
    ["B", "Qalin (Ctrl+B)", () => c().toggleBold().run(), () => editor.isActive("bold")],
    ["I", "Qiya (Ctrl+I)", () => c().toggleItalic().run(), () => editor.isActive("italic")],
    ["U", "Tagiga chizilgan", () => c().toggleUnderline().run(), () => editor.isActive("underline")],
    ["S", "Ustidan chizilgan", () => c().toggleStrike().run(), () => editor.isActive("strike")],
    ["▨", "Belgilab ko'rsatish", () => c().toggleHighlight().run(), () => editor.isActive("highlight")],
    "|",
    ["H2", "Sarlavha 2", () => c().toggleHeading({ level: 2 }).run(), () => editor.isActive("heading", { level: 2 })],
    ["H3", "Sarlavha 3", () => c().toggleHeading({ level: 3 }).run(), () => editor.isActive("heading", { level: 3 })],
    ["¶", "Oddiy matn", () => c().setParagraph().run(), () => editor.isActive("paragraph")],
    "|",
    ["• ", "Belgilangan ro'yxat", () => c().toggleBulletList().run(), () => editor.isActive("bulletList")],
    ["1.", "Raqamlangan ro'yxat", () => c().toggleOrderedList().run(), () => editor.isActive("orderedList")],
    ["❝", "Iqtibos", () => c().toggleBlockquote().run(), () => editor.isActive("blockquote")],
    "|",
    ["⇤", "Chapga", () => c().setTextAlign("left").run(), () => editor.isActive({ textAlign: "left" })],
    ["↔", "Markazga", () => c().setTextAlign("center").run(), () => editor.isActive({ textAlign: "center" })],
    ["⇥", "O'ngga", () => c().setTextAlign("right").run(), () => editor.isActive({ textAlign: "right" })],
    "|",
    ["</>", "Kod (satr ichida)", () => c().toggleCode().run(), () => editor.isActive("code")],
    ["{ }", "Kod bloki", () => c().toggleCodeBlock().run(), () => editor.isActive("codeBlock")],
    "lang",
    "|",
    ["🔗", "Havola", () => {
      const prev = editor.getAttributes("link").href || "https://";
      const url = prompt("Havola manzili (bo'sh qoldirsangiz o'chadi):", prev);
      if (url === null) return;
      if (url === "" || url === "https://") c().unsetLink().run(); else c().extendMarkRange("link").setLink({ href: url }).run();
    }, () => editor.isActive("link")],
    ["🖼", "Rasm yuklash", () => {
      const input = el("input"); input.type = "file"; input.accept = "image/*";
      input.onchange = () => input.files[0] && insertImageFile(editor, input.files[0]);
      input.click();
    }, () => false],
    ["▶", "YouTube video", () => {
      const url = prompt("YouTube havolasi:");
      if (url) c().setYoutubeVideo({ src: url }).run();
    }, () => false],
    ["▦", "Jadval", () => c().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(), () => editor.isActive("table")],
    "table",
    ["―", "Gorizontal chiziq", () => c().setHorizontalRule().run(), () => false],
    "|",
    ["↶", "Bekor qilish", () => c().undo().run(), () => false],
    ["↷", "Qaytarish", () => c().redo().run(), () => false],
    ["✕", "Formatni tozalash", () => c().clearNodes().unsetAllMarks().run(), () => false],
  ];

  const buttons = [];
  let langSelect = null, tableBox = null;
  for (const it of items) {
    if (it === "|") { toolbar.append(el("span", "rte-sep")); continue; }
    if (it === "lang") {
      langSelect = el("select", "rte-select");
      LANGS.forEach(([v, t]) => { const o = el("option", "", t); o.value = v; langSelect.append(o); });
      langSelect.title = "Kod bloki tili";
      langSelect.onchange = () => editor.chain().focus().updateAttributes("codeBlock", { language: langSelect.value || null }).run();
      toolbar.append(langSelect);
      continue;
    }
    if (it === "table") {
      tableBox = el("span", "rte-tablebox");
      [["+Q", "Qator qo'shish", () => c().addRowAfter().run()], ["-Q", "Qatorni o'chirish", () => c().deleteRow().run()],
       ["+U", "Ustun qo'shish", () => c().addColumnAfter().run()], ["-U", "Ustunni o'chirish", () => c().deleteColumn().run()],
       ["✕▦", "Jadvalni o'chirish", () => c().deleteTable().run()]].forEach(([l, t, f]) => {
        const b = el("button", "rte-btn", l); b.type = "button"; b.title = t; b.onclick = (e) => { e.preventDefault(); f(); }; tableBox.append(b);
      });
      toolbar.append(tableBox);
      continue;
    }
    const [label, title, run, active] = it;
    const b = el("button", "rte-btn", label);
    b.type = "button"; b.title = title;
    b.onmousedown = (e) => e.preventDefault();
    b.onclick = (e) => { e.preventDefault(); run(); };
    toolbar.append(b);
    buttons.push([b, active]);
  }

  const refresh = () => {
    buttons.forEach(([b, active]) => b.classList.toggle("active", !!active()));
    if (tableBox) tableBox.style.display = editor.isActive("table") ? "inline-flex" : "none";
    if (langSelect) {
      const inCode = editor.isActive("codeBlock");
      langSelect.style.display = inCode ? "" : "none";
      if (inCode) langSelect.value = editor.getAttributes("codeBlock").language || "";
    }
  };
  editor.on("transaction", refresh);
  refresh();

  const form = textarea.closest("form");
  if (form) form.addEventListener("submit", () => { textarea.value = editor.isEmpty ? "" : editor.getHTML(); });
}

export function initRichEditors(root = document) {
  root.querySelectorAll("textarea[data-rich]").forEach(build);
}
window.initRichEditors = initRichEditors;
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => initRichEditors());
else initRichEditors();
