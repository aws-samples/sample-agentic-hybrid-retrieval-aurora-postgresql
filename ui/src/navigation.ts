import {
  useLocation,
  useSearchParams as useWouterSearchParams,
} from "wouter";

type NavigationOptions = {
  replace?: boolean;
};

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
