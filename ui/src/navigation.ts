import {
  useLocation,
  useSearchParams as useWouterSearchParams,
} from "wouter";

type NavigationOptions = {
  replace?: boolean;
};

/**
 * The retrieval surface's route and the one name for it.
 *
 * Three places spelled this name and they disagreed: the header said "Retrieval
 * Observatory", the Labs tab strip said the same, and the Discover band's kicker
 * said "Mosaic Labs" directly above a button reading "Open Retrieval
 * Observatory" — three names for one destination, two of them on one screen.
 */
export const RETRIEVAL_SURFACE = {
  path: "/labs/retrieval",
  label: "Retrieval Observatory",
} as const;

export function useNavigate() {
  const [, navigate] = useLocation();
  return (to: string, options?: NavigationOptions) => navigate(to, options);
}

export function useSearchParams(): [
  URLSearchParams,
  (params: URLSearchParams, options?: NavigationOptions) => void,
] {
  const [params, setParams] = useWouterSearchParams();
  return [params, setParams];
}
