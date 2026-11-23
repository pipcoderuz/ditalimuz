// Tayyor kutubxonalarni static/dist ga ko'chiradi (CDN'ga bog'liq bo'lmaslik uchun)
const fs = require("fs");
const copies = [
  ["node_modules/flowbite/dist/flowbite.min.js", "static/dist/flowbite.min.js"],
  ["node_modules/chart.js/dist/chart.umd.min.js", "static/dist/chart.umd.min.js"],
];
for (const [src, dst] of copies) { fs.copyFileSync(src, dst); console.log("copied", dst); }
