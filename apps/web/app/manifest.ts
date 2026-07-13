import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "OpenCarDueDiligence",
    short_name: "OpenCarDD",
    description: "Evidence-led used-car due diligence",
    start_url: "/",
    display: "standalone",
    background_color: "#f3f0e9",
    theme_color: "#102b2b",
    categories: ["automotive", "finance", "utilities"],
    icons: [
      { src: "/pwa-icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/pwa-icon-maskable.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" }
    ]
  };
}
