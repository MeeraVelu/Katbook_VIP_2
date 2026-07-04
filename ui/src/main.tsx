import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createBrowserRouter, Navigate } from "react-router-dom";
import { queryClient } from "@/lib/queryClient";
import { Layout } from "@/components/Layout";
import { Library } from "@/pages/Library";
import { VideoDetail } from "@/pages/VideoDetail";
import { Search } from "@/pages/Search";
import { Ingest } from "@/pages/Ingest";
import { Jobs } from "@/pages/Jobs";
import { JobDetail } from "@/pages/JobDetail";
import { System } from "@/pages/System";
import "./index.css";

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/library" replace /> },
      { path: "/library", element: <Library /> },
      { path: "/videos/:id", element: <VideoDetail /> },
      { path: "/search", element: <Search /> },
      { path: "/ingest", element: <Ingest /> },
      { path: "/jobs", element: <Jobs /> },
      { path: "/jobs/:id", element: <JobDetail /> },
      { path: "/system", element: <System /> },
      { path: "*", element: <Navigate to="/library" replace /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
);
