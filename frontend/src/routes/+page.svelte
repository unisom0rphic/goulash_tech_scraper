<script lang="ts">
  interface SupplierCard {
    id: string;
    name: string;
    contacts: string;
    website?: string | null;
    source?: string | null;
    price?: string | null;
    min_order?: string | null;
    certificates: string[];
    delivery_conditions?: string | null;
    region_covered?: string | null;
    comment?: string | null;
  }

  interface SearchResponse {
    search_id: string;
    status: "processing" | "completed" | "failed";
    results?: SupplierCard[];
    scores?: number[];
    error?: string;
  }

  // Состояние (runes)
  let query = $state("");
  let region = $state("");
  let limit = $state(5);
  let searchId = $state<string | null>(null);
  let status = $state<"idle" | "processing" | "completed" | "failed">("idle");
  let results = $state<SupplierCard[]>([]);
  let scores = $state<number[]>([]);
  let error = $state("");
  let polling = $state<ReturnType<typeof setInterval> | null>(null);

  // Производное значение (derived)
  let searchUrl = $derived(
    searchId ? `http://localhost:8000/search/${searchId}/results` : null
  );

  const API_BASE = "http://localhost:8000";

  async function startSearch() {
    if (!query || !region) return;
    error = "";
    results = [];
    scores = [];
    status = "processing";
    try {
      const res = await fetch(`${API_BASE}/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, region, limit }),
      });
      if (!res.ok) throw new Error("Search creation failed");
      const data: SearchResponse = await res.json();
      searchId = data.search_id;
      startPolling();
    } catch (e) {
      status = "failed";
      error = e instanceof Error ? e.message : "Unknown error";
    }
  }

  function startPolling() {
    if (polling) clearInterval(polling);
    polling = setInterval(async () => {
      if (!searchUrl) return;
      try {
        const res = await fetch(searchUrl);
        const data: SearchResponse = await res.json();
        if (data.status === "completed") {
          results = data.results ?? [];
          scores = data.scores ?? [];
          status = "completed";
          clearInterval(polling!);
          polling = null;
        } else if (data.status === "failed") {
          status = "failed";
          error = data.error ?? "Unknown error";
          clearInterval(polling!);
          polling = null;
        }
      } catch (e) {
        status = "failed";
        error = "Connection error";
        clearInterval(polling!);
        polling = null;
      }
    }, 2000);
  }

  async function addComment(resultId: string) {
    const comment = prompt("Add comment:");
    if (comment && searchId) {
      await fetch(
        `${API_BASE}/results/${searchId}/${resultId}/comment?comment=${encodeURIComponent(comment)}`,
        { method: "PATCH" }
      );
      // Обновим данные из API
      const res = await fetch(searchUrl!);
      const data: SearchResponse = await res.json();
      results = data.results ?? [];
      scores = data.scores ?? [];
    }
  }

  function downloadCsv() {
    if (searchId) {
      window.open(`${API_BASE}/search/${searchId}/export`, "_blank");
    }
  }
</script>

<main>
  <h1>Supplier Search</h1>
  <form onsubmit={startSearch}>
    <input type="text" bind:value={query} placeholder="Что ищем (мука, упаковка...)" required />
    <input type="text" bind:value={region} placeholder="Регион (Москва, СПб...)" required />
    <input type="number" bind:value={limit} min="1" max="20" />
    <button type="submit">Найти</button>
  </form>

  {#if status === "processing"}
    <p>Ищем поставщиков... ожидайте.</p>
  {/if}

  {#if status === "failed"}
    <p class="error">Ошибка: {error}</p>
  {/if}

  {#if status === "completed" && results.length > 0}
    <button onclick={downloadCsv}>Скачать CSV</button>
    <table>
      <thead>
        <tr>
          <th>Score</th>
          <th>Name</th>
          <th>Contacts</th>
          <th>Price</th>
          <th>Certificates</th>
          <th>Comment</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        {#each results as card, i}
          <tr>
            <td>{scores[i]?.toFixed(2)}</td>
            <td>{card.name}</td>
            <td>{card.contacts}</td>
            <td>{card.price || "—"}</td>
            <td>{card.certificates?.join(", ") || "—"}</td>
            <td>{card.comment ?? ""}</td>
            <td><button onclick={() => addComment(card.id)}>Добавить заметку</button></td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else if status === "completed"}
    <p>Ничего не найдено.</p>
  {/if}
</main>

<style>
  :global(body) {
    background: #111;
    color: #eee;
    font-family: system-ui;
    padding: 2rem;
  }
  form {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 2rem;
  }
  input,
  button {
    padding: 0.5rem;
    background: #222;
    color: white;
    border: 1px solid #444;
    border-radius: 4px;
  }
  button {
    cursor: pointer;
    background: #333;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 1rem;
  }
  th,
  td {
    border: 1px solid #444;
    padding: 0.5rem;
    text-align: left;
  }
  th {
    background: #1a1a1a;
  }
  .error {
    color: #f66;
  }
</style>