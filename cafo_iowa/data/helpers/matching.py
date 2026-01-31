import logging
from typing import Dict, List, Optional, Tuple, Union

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from fuzzywuzzy import fuzz
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class BaseMatcher:
    """Base class for feature matching strategies."""

    def __init__(
        self,
        gdf: gpd.GeoDataFrame,
        grouping_columns: List[str],
        buffer_distance: float = 0,
        missing_values_action: str = "exclude",
    ):
        self.gdf = gdf
        self.grouping_columns = grouping_columns
        self.buffer_distance = buffer_distance
        self.missing_values_action = missing_values_action
        self.original_rows = len(gdf)
        # Determine the ID column or fallback to index
        self.id_col = "id" if "id" in gdf.columns else None

    def handle_missing_values(self) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
        """Handle missing values in grouping columns."""
        if self.grouping_columns:
            missing_or_empty_mask = (
                self.gdf[self.grouping_columns].isna()
                | (
                    self.gdf[self.grouping_columns]
                    .astype(str)
                    .apply(lambda x: x.str.strip() == "")
                )
            ).any(axis=1)

            if self.missing_values_action == "exclude":
                gdf_with_values = self.gdf[~missing_or_empty_mask].copy()
                gdf_missing_values = self.gdf[missing_or_empty_mask].copy()
            elif self.missing_values_action == "include":
                gdf_with_values = self.gdf.copy()
                gdf_missing_values = gpd.GeoDataFrame(
                    columns=self.gdf.columns, crs=self.gdf.crs
                )
            else:
                raise ValueError("missing_values_action must be 'exclude' or 'include'")
        else:
            gdf_with_values = self.gdf.copy()
            gdf_missing_values = gpd.GeoDataFrame(
                columns=self.gdf.columns, crs=self.gdf.crs
            )

        return gdf_with_values, gdf_missing_values

    def prepare_spatial_data(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Convert to UTM and prepare spatial data."""
        utm_crs = gdf.estimate_utm_crs()
        gdf_utm = gdf.to_crs(utm_crs)

        if self.buffer_distance > 0:
            gdf_utm["geometry_buffer"] = gdf_utm.geometry.buffer(self.buffer_distance)
        else:
            gdf_utm["geometry_buffer"] = gdf_utm.geometry

        return gdf_utm

    def build_spatial_graph(self, gdf_utm: gpd.GeoDataFrame) -> nx.Graph:
        """Build spatial graph for finding nearby features."""
        sindex = gdf_utm.sindex
        G = nx.Graph()
        G.add_nodes_from(range(len(gdf_utm)))

        for idx in range(len(gdf_utm)):
            geom = gdf_utm.geometry.iloc[idx]
            possible_matches = list(
                sindex.intersection(geom.buffer(self.buffer_distance).bounds)
            )
            possible_matches = [i for i in possible_matches if i != idx]

            for other_idx in possible_matches:
                if (
                    geom.distance(gdf_utm.geometry.iloc[other_idx])
                    <= self.buffer_distance
                ):
                    if self.should_merge_features(gdf_utm, idx, other_idx):
                        G.add_edge(idx, other_idx)

        return G

    def should_merge_features(
        self, gdf: gpd.GeoDataFrame, idx1: int, idx2: int
    ) -> bool:
        """Determine if two features should be merged. To be implemented by subclasses."""
        raise NotImplementedError

    def merge_features(
        self, gdf: gpd.GeoDataFrame, sub_groups: pd.DataFrame
    ) -> gpd.GeoDataFrame:
        """Merge features in a sub-group into a single feature."""
        # Get the indices from the sub_groups
        indices = sub_groups.index.tolist()

        # Get the geometries for these indices from the original GeoDataFrame
        geometries = gdf.geometry.iloc[indices]

        # Merge geometries
        merged_geom = geometries.unary_union

        # Combine original IDs from sub-groups
        original_ids = self.combine_original_ids(sub_groups)

        # Calculate features_merged - if column exists, sum it up; otherwise count features
        features_merged_val = (
            sub_groups["features_merged"].sum()
            if "features_merged" in sub_groups.columns
            else len(sub_groups)
        )

        # Create a dictionary for the merged feature
        feature_dict = {
            "geometry": [merged_geom],
            "original_ids": [original_ids],
            "features_merged": [features_merged_val],
        }

        # Add other columns from the first row of sub_groups
        for col in gdf.columns:
            if col not in ["geometry", "original_ids", "features_merged"]:
                feature_dict[col] = [gdf[col].iloc[indices[0]]]

        # Create merged feature
        merged_features = gpd.GeoDataFrame(feature_dict, crs=gdf.crs)

        return merged_features

    def combine_original_ids(self, sub_groups: pd.DataFrame) -> List[int]:
        """Combine original IDs from sub-groups into a single list."""
        # If original_ids already exists, we combine them
        if "original_ids" in sub_groups.columns:
            # Combine all lists of original_ids from the sub_group
            combined_ids = []
            for val in sub_groups["original_ids"]:
                # Ensure that val is a list
                if isinstance(val, list):
                    combined_ids.extend(val)
                else:
                    combined_ids.append(val)
            return list(set(combined_ids))  # Remove duplicates
        else:
            # If no original_ids column, create from current IDs
            if self.id_col:
                return sub_groups[self.id_col].tolist()
            else:
                return sub_groups.index.tolist()

    def process(self) -> gpd.GeoDataFrame:
        """Process the matching strategy."""
        # Handle missing values
        gdf_with_values, gdf_missing_values = self.handle_missing_values()

        # Prepare spatial data
        gdf_utm = self.prepare_spatial_data(gdf_with_values)

        # Build spatial graph
        G = self.build_spatial_graph(gdf_utm)

        # Get connected components from the graph
        merged_features = []

        # Sort components by the minimum ID in each component to ensure deterministic processing
        components = list(nx.connected_components(G))
        sorted_components = sorted(components, key=lambda c: min(c))

        for component in sorted_components:
            # Convert component to list of indices
            indices = list(component)

            # Get the actual rows from gdf_utm using the indices
            sub_groups = gdf_utm.iloc[indices].copy()

            # Ensure the index matches the original indices
            sub_groups.index = indices

            # Merge features in this component
            merged_feature = self.merge_features(gdf_utm, sub_groups)
            merged_features.append(merged_feature)

        # Handle missing values
        if not gdf_missing_values.empty:
            # If original_ids already exists, combine them; otherwise, use ID or index
            if "original_ids" in gdf_missing_values.columns:
                # already has original_ids, just ensure it's a list
                gdf_missing_values["original_ids"] = gdf_missing_values[
                    "original_ids"
                ].apply(lambda x: x if isinstance(x, list) else [x])
            else:
                if self.id_col:
                    gdf_missing_values["original_ids"] = gdf_missing_values[
                        self.id_col
                    ].apply(lambda x: [x])
                else:
                    gdf_missing_values["original_ids"] = (
                        gdf_missing_values.index.to_series().apply(lambda x: [x])
                    )

            # If features_merged exists, use it; otherwise set to 1
            if "features_merged" not in gdf_missing_values.columns:
                gdf_missing_values["features_merged"] = 1

            # Ensure missing values GeoDataFrame has the same CRS as gdf_utm
            gdf_missing_values = gdf_missing_values.to_crs(gdf_utm.crs)
            merged_features.append(gdf_missing_values)

        # Combine all merged features and reproject to original CRS
        result = gpd.GeoDataFrame(
            pd.concat(merged_features, ignore_index=True), crs=gdf_utm.crs
        )
        result = result.to_crs(self.gdf.crs)

        # Log results
        merged_rows = self.original_rows - len(result)
        logging.info(f"{merged_rows} rows were merged using {self.__class__.__name__}")

        return result


class ExactMatcher(BaseMatcher):
    """Matcher that uses exact matching of grouping columns."""

    def __init__(
        self,
        gdf: gpd.GeoDataFrame,
        grouping_columns: List[str],
        buffer_distance: float = 0,
        missing_values_action: str = "exclude",
    ):
        super().__init__(gdf, grouping_columns, buffer_distance, missing_values_action)
        self.matching_records = []  # Store matching records

    def should_merge_features(
        self, gdf: gpd.GeoDataFrame, idx1: int, idx2: int
    ) -> bool:
        if not self.grouping_columns:
            return True

        for col in self.grouping_columns:
            val1 = gdf[col].iloc[idx1]
            val2 = gdf[col].iloc[idx2]

            # Skip matching if either value is the placeholder for missing names
            if (
                pd.isna(val1)
                or pd.isna(val2)
                or val1 == "MISSING_NAME_PLACEHOLDER"
                or val2 == "MISSING_NAME_PLACEHOLDER"
            ):
                return False

            # Record the matching attempt
            self.matching_records.append(
                {
                    "original_id": gdf.index[idx1],
                    "matched_id": gdf.index[idx2],
                    "original_value": val1,
                    "matched_value": val2,
                    "matched": str(val1) == str(val2),
                    "match_type": "exact",
                }
            )

            if str(val1) != str(val2):
                return False
        return True

    def process(self) -> gpd.GeoDataFrame:
        """Process the matching strategy and save records."""
        result = super().process()

        # Save matching records to CSV
        if self.matching_records:
            records_df = pd.DataFrame(self.matching_records)
            records_df.to_csv("output/matching/exact_matching_records.csv", index=False)
            logging.info(
                f"Saved exact matching records to output/matching/exact_matching_records.csv"
            )

        return result


class FuzzyMatcher(BaseMatcher):
    """Matcher that uses fuzzy matching of grouping columns."""

    def __init__(
        self,
        gdf: gpd.GeoDataFrame,
        grouping_columns: List[str],
        buffer_distance: float = 0,
        threshold: float = 80,
        missing_values_action: str = "exclude",
        words_to_remove: Optional[List[str]] = None,
    ):
        super().__init__(gdf, grouping_columns, buffer_distance, missing_values_action)
        self.threshold = threshold
        self.words_to_remove = words_to_remove or []
        self.matching_records = []  # Store matching records

    def clean_text(self, text: str) -> str:
        """Remove specified words from text and standardize name formats."""
        if not isinstance(text, str):
            return str(text)

        # Convert to uppercase for consistency
        text = text.upper()

        # Replace common separators with spaces
        text = text.replace("&", " ")
        text = text.replace(",", " ")
        text = text.replace(".", " ")
        text = " ".join(text.split())

        # Split into words
        words = text.split()

        # Remove specified business words
        words = [w for w in words if w not in self.words_to_remove]

        # Handle potential initials by removing single letters
        # But keep them if they're the only word or if the text is very short (<=4 chars)
        if len(words) > 1 and len(text) > 4:
            words = [w for w in words if len(w) > 1]

        # Remove duplicated words (like repeated last names)
        words = list(dict.fromkeys(words))

        # Join back together
        return " ".join(words)

    def should_merge_features(
        self, gdf: gpd.GeoDataFrame, idx1: int, idx2: int
    ) -> bool:
        """Check if features should be merged based on fuzzy matching."""
        # Sort indices to ensure consistent comparison order
        idx1, idx2 = min(idx1, idx2), max(idx1, idx2)

        for col in self.grouping_columns:
            val1 = self.clean_text(gdf[col].iloc[idx1])
            val2 = self.clean_text(gdf[col].iloc[idx2])

            # Skip matching if either value is the placeholder for missing names
            if val1 == "MISSING_NAME_PLACEHOLDER" or val2 == "MISSING_NAME_PLACEHOLDER":
                return False

            # If either string is empty after cleaning, don't match
            if not val1 or not val2:
                return False

            # Don't match if one name is very short (<=4 chars) and the other is much longer
            len1, len2 = len(val1), len(val2)
            if (len1 <= 4 or len2 <= 4) and abs(len1 - len2) > 3:
                return False

            # Calculate both similarity scores
            token_sort_score = fuzz.token_sort_ratio(val1, val2)
            partial_score = fuzz.partial_ratio(val1, val2)
            best_score = max(token_sort_score, partial_score)

            # Record the matching attempt
            self.matching_records.append(
                {
                    "original_id": gdf.index[idx1],
                    "matched_id": gdf.index[idx2],
                    "original_value": gdf[col].iloc[idx1],
                    "matched_value": gdf[col].iloc[idx2],
                    "original_value_clean": val1,
                    "matched_value_clean": val2,
                    "token_sort_score": token_sort_score,
                    "partial_score": partial_score,
                    "best_score": best_score,
                    "threshold": self.threshold,
                    "matched": best_score >= self.threshold,
                    "match_type": "fuzzy",
                }
            )

            # Use token_sort_ratio for better matching of differently ordered words
            if token_sort_score < self.threshold:
                # Try partial ratio as a fallback for cases where one name is a subset of the other
                if partial_score < self.threshold:
                    return False
        return True

    def process(self) -> gpd.GeoDataFrame:
        """Process the matching strategy and save records."""
        result = super().process()

        # Save matching records to CSV
        if self.matching_records:
            records_df = pd.DataFrame(self.matching_records)
            records_df.to_csv("output/matching/fuzzy_matching_records.csv", index=False)
            logging.info(
                f"Saved fuzzy matching records to output/matching/fuzzy_matching_records.csv"
            )

        return result


class TfidfMatcher(BaseMatcher):
    """Matcher that uses TF-IDF similarity of grouping columns."""

    def __init__(
        self,
        gdf: gpd.GeoDataFrame,
        grouping_columns: List[str],
        buffer_distance: float = 0,
        similarity_threshold: float = 0.8,
        missing_values_action: str = "exclude",
    ):
        super().__init__(gdf, grouping_columns, buffer_distance, missing_values_action)
        self.similarity_threshold = similarity_threshold
        self.vectorizers = {}
        self.tfidf_matrices = {}
        self.matching_records = []  # Store matching records

    def prepare_spatial_data(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        gdf_utm = super().prepare_spatial_data(gdf)

        # Create TF-IDF vectors for each grouping column
        for col in self.grouping_columns:
            self.vectorizers[col] = TfidfVectorizer(
                analyzer="word", ngram_range=(1, 1), min_df=1
            )
            self.tfidf_matrices[col] = self.vectorizers[col].fit_transform(
                gdf_utm[col].astype(str)
            )

        return gdf_utm

    def should_merge_features(
        self, gdf: gpd.GeoDataFrame, idx1: int, idx2: int
    ) -> bool:
        match_results = []
        for col in self.grouping_columns:
            # Get vectors for the two features
            vec1 = self.tfidf_matrices[col][idx1 : idx1 + 1]
            vec2 = self.tfidf_matrices[col][idx2 : idx2 + 1]

            # Skip matching if either value is the placeholder for missing names
            val1 = gdf[col].iloc[idx1]
            val2 = gdf[col].iloc[idx2]
            if (
                pd.isna(val1)
                or pd.isna(val2)
                or val1 == "MISSING_NAME_PLACEHOLDER"
                or val2 == "MISSING_NAME_PLACEHOLDER"
            ):
                return False

            # Calculate cosine similarity
            similarity = cosine_similarity(vec1, vec2)[0][0]
            match_results.append(similarity >= self.similarity_threshold)

            # Record the matching attempt
            self.matching_records.append(
                {
                    "original_id": gdf.index[idx1],
                    "matched_id": gdf.index[idx2],
                    "original_value": gdf[col].iloc[idx1],
                    "matched_value": gdf[col].iloc[idx2],
                    "similarity_score": similarity,
                    "threshold": self.similarity_threshold,
                    "matched": similarity >= self.similarity_threshold,
                    "match_type": "tfidf",
                }
            )

        return all(match_results)

    def process(self) -> gpd.GeoDataFrame:
        """Process the matching strategy and save records."""
        result = super().process()

        # Save matching records to CSV
        if self.matching_records:
            records_df = pd.DataFrame(self.matching_records)
            records_df.to_csv("output/matching/tfidf_matching_records.csv", index=False)
            logging.info(
                f"Saved TF-IDF matching records to output/matching/tfidf_matching_records.csv"
            )

        return result


def exact_match(
    gdf: gpd.GeoDataFrame,
    grouping_columns: List[str],
    buffer_distance: float = 0,
    missing_values_action: str = "exclude",
) -> gpd.GeoDataFrame:
    """Merge features based on exact matching of grouping columns."""
    matcher = ExactMatcher(
        gdf, grouping_columns, buffer_distance, missing_values_action
    )
    return matcher.process()


def fuzzy_match(
    gdf: gpd.GeoDataFrame,
    grouping_columns: List[str],
    buffer_distance: float = 0,
    threshold: float = 80,
    missing_values_action: str = "exclude",
    words_to_remove: Optional[List[str]] = None,
) -> gpd.GeoDataFrame:
    """Merge features based on fuzzy matching of grouping columns.

    Args:
        gdf: Input GeoDataFrame
        grouping_columns: Columns to match on
        buffer_distance: Distance in meters to consider features as "nearby"
        threshold: Fuzzy matching threshold (0-100)
        missing_values_action: How to handle missing values ('exclude' or 'include')
        words_to_remove: List of words to remove before matching
    """
    matcher = FuzzyMatcher(
        gdf,
        grouping_columns,
        buffer_distance,
        threshold,
        missing_values_action,
        words_to_remove,
    )
    return matcher.process()


def tfidf_match(
    gdf: gpd.GeoDataFrame,
    grouping_columns: List[str],
    buffer_distance: float = 0,
    similarity_threshold: float = 0.8,
    missing_values_action: str = "exclude",
) -> gpd.GeoDataFrame:
    """Merge features based on TF-IDF similarity of grouping columns."""
    matcher = TfidfMatcher(
        gdf,
        grouping_columns,
        buffer_distance,
        similarity_threshold,
        missing_values_action,
    )
    return matcher.process()


def check_fuzzy_match(val1: str, val2: str, rules: Dict) -> bool:
    """Helper function to check if two values match according to fuzzy matching rules."""
    method = rules.get("method", "ratio")
    threshold = rules.get("threshold", 80)

    if method == "ratio":
        return fuzz.ratio(val1, val2) >= threshold
    elif method == "partial_ratio":
        return fuzz.partial_ratio(val1, val2) >= threshold
    elif method == "token_sort_ratio":
        return fuzz.token_sort_ratio(val1, val2) >= threshold
    elif method == "token_set_ratio":
        return fuzz.token_set_ratio(val1, val2) >= threshold
    else:
        return fuzz.ratio(val1, val2) >= threshold
