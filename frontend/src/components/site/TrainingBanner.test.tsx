import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as siteApi from "../../api/site";
import { renderWithProviders } from "../../test/render";
import { TrainingBanner } from "./TrainingBanner";

vi.mock("../../api/site");

describe("eğitim ortamı şeridi", () => {
  it("eğitim ortamında uyarıyı gösterir", async () => {
    vi.mocked(siteApi.fetchSiteInfo).mockResolvedValue({ training_mode: true });
    renderWithProviders(<TrainingBanner />);
    expect(await screen.findByRole("status")).toHaveTextContent("EĞİTİM ORTAMI");
  });

  it("canlı ortamda hiçbir şey göstermez", async () => {
    const spy = vi.mocked(siteApi.fetchSiteInfo).mockResolvedValue({ training_mode: false });
    renderWithProviders(<TrainingBanner />);
    await vi.waitFor(() => expect(spy).toHaveBeenCalled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
