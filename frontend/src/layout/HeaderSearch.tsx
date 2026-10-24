import { ActionIcon } from "@mantine/core";
import { IconSearch } from "@tabler/icons-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { SEARCH_PATH, searchPath } from "../auth/paths";
import { tr } from "../i18n/tr";
import classes from "./AppLayout.module.css";

/**
 * Üst çubuktaki arama (DentMesher'daki gibi her rolde aynı yerde): Enter sonuç sayfasını açar.
 * Dar ekranda yalnızca simge görünür ve arama sayfasına götürür.
 */
export function HeaderSearch() {
  const [query, setQuery] = useState("");
  const navigate = useNavigate();

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    navigate(searchPath(query));
    setQuery("");
  }

  return (
    <>
      <form className={classes.search} role="search" onSubmit={submit}>
        <IconSearch size={16} aria-hidden="true" />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
          placeholder={tr.layout.search}
          aria-label={tr.layout.search}
        />
      </form>
      <ActionIcon
        component={Link}
        to={SEARCH_PATH}
        variant="subtle"
        color="gray"
        size="xl"
        radius="xl"
        aria-label={tr.layout.search}
        className={classes.searchIcon}
      >
        <IconSearch size={22} />
      </ActionIcon>
    </>
  );
}
