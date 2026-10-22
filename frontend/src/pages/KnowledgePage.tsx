import React, { useEffect, useState, useCallback } from 'react';
import { listRunbooks, uploadRunbookFile, searchKnowledge } from '../api/knowledge';
import { KnowledgeDocument, RetrievedChunk } from '../../types/knowledge';
import { getErrorMessage } from '../api/client';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { ErrorAlert } from '../components/common/ErrorAlert';
import {
  BookOpen,
  UploadCloud,
  Search,
  CheckCircle2,
  FileCode,
  Layers,
  Sparkles,
  RefreshCw,
} from 'lucide-react';

export const KnowledgePage: React.FC = () => {
  const [runbooks, setRunbooks] = useState<KnowledgeDocument[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Upload state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploadService, setUploadService] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<RetrievedChunk[] | null>(null);

  const fetchRunbooks = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await listRunbooks(50, 0);
      setRunbooks(data);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRunbooks();
  }, [fetchRunbooks]);

  const handleFileUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) return;

    setIsUploading(true);
    setUploadSuccess(null);
    setError(null);

    try {
      const doc = await uploadRunbookFile(
        selectedFile,
        uploadTitle || undefined,
        uploadService || undefined
      );
      setUploadSuccess(
        `Successfully ingested "${doc.title}" into vector index (${doc.chunk_count} chunks generated).`
      );
      setSelectedFile(null);
      setUploadTitle('');
      setUploadService('');
      fetchRunbooks();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsUploading(false);
    }
  };

  const handleSemanticSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;

    setIsSearching(true);
    setError(null);
    try {
      const results = await searchKnowledge({
        query: searchQuery.trim(),
        top_k: 4,
        min_similarity: 0.1,
      });
      setSearchResults(results);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold font-mono text-white tracking-tight flex items-center">
            <BookOpen className="w-6 h-6 mr-2.5 text-cyan-400" />
            Operational Runbook RAG Index
          </h1>
          <p className="mt-1 text-xs sm:text-sm text-slate-400 font-mono">
            Vector embeddings (384-dim) & operational SOP ingestion for AI investigation grounding
          </p>
        </div>
        <button
          onClick={fetchRunbooks}
          disabled={isLoading}
          className="p-2 text-slate-300 hover:text-white bg-sre-900 border border-slate-800 rounded-lg hover:bg-slate-850 self-start sm:self-auto"
          title="Refresh runbooks"
        >
          <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {error && <ErrorAlert title="Knowledge Base Error" message={error} />}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Upload Markdown SOP (1 col) */}
        <div className="rounded-xl border border-slate-800 bg-sre-900/60 p-6 shadow-xl space-y-4">
          <div className="flex items-center space-x-2 border-b border-slate-800 pb-3">
            <UploadCloud className="w-5 h-5 text-cyan-400" />
            <h2 className="text-sm font-semibold font-mono text-white">Upload Runbook Document</h2>
          </div>

          {uploadSuccess && (
            <div className="p-3 bg-emerald-950/60 border border-emerald-800 rounded-lg text-emerald-300 text-xs font-mono flex items-start">
              <CheckCircle2 className="w-4 h-4 mr-2 text-emerald-400 flex-shrink-0 mt-0.5" />
              <span>{uploadSuccess}</span>
            </div>
          )}

          <form onSubmit={handleFileUpload} className="space-y-4">
            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1">
                Markdown / SOP File (.md, .txt, .json)
              </label>
              <input
                type="file"
                required
                accept=".md,.txt,.json,.markdown"
                onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                className="w-full text-xs text-slate-400 font-mono file:mr-3 file:py-2 file:px-3 file:rounded-md file:border-0 file:text-xs file:font-mono file:font-semibold file:bg-cyan-950 file:text-cyan-300 hover:file:bg-cyan-900 cursor-pointer"
              />
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1">
                Document Title (Optional)
              </label>
              <input
                type="text"
                placeholder="e.g. Postgres Connection Pool Runbook"
                value={uploadTitle}
                onChange={(e) => setUploadTitle(e.target.value)}
                className="w-full px-3 py-2 text-xs bg-sre-950 border border-slate-800 rounded-lg text-slate-200 font-mono"
              />
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1">
                Microservice Scope (Optional)
              </label>
              <input
                type="text"
                placeholder="e.g. billing-service"
                value={uploadService}
                onChange={(e) => setUploadService(e.target.value)}
                className="w-full px-3 py-2 text-xs bg-sre-950 border border-slate-800 rounded-lg text-slate-200 font-mono"
              />
            </div>

            <button
              type="submit"
              disabled={isUploading || !selectedFile}
              className="w-full py-2.5 px-4 text-xs font-mono font-semibold rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white disabled:opacity-50 transition-colors shadow-md shadow-cyan-950/40"
            >
              {isUploading ? 'Chunking & Embedding...' : 'Ingest into Vector Store'}
            </button>
          </form>
        </div>

        {/* Right Column: Semantic Vector Search & Indexed Runbooks (2 cols) */}
        <div className="lg:col-span-2 space-y-6">
          {/* Semantic Search Tester */}
          <div className="rounded-xl border border-slate-800 bg-sre-900/60 p-6 shadow-xl space-y-4">
            <div className="flex items-center space-x-2 border-b border-slate-800 pb-3">
              <Sparkles className="w-5 h-5 text-purple-400" />
              <h2 className="text-sm font-semibold font-mono text-white">
                Test Semantic Vector Retrieval
              </h2>
            </div>

            <form onSubmit={handleSemanticSearch} className="flex gap-2">
              <div className="relative flex-1">
                <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
                <input
                  type="text"
                  placeholder="Ask a technical query (e.g. 'How to restart payment worker on OOM?')..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 text-xs bg-sre-950 border border-slate-800 rounded-lg text-slate-100 placeholder-slate-500 font-mono focus:border-purple-500 focus:outline-none"
                />
              </div>
              <button
                type="submit"
                disabled={isSearching || !searchQuery.trim()}
                className="px-4 py-2 text-xs font-mono font-semibold rounded-lg bg-purple-600 hover:bg-purple-500 text-white disabled:opacity-50 shadow-md shadow-purple-950/40"
              >
                {isSearching ? 'Querying...' : 'Search Vectors'}
              </button>
            </form>

            {/* Results display */}
            {searchResults && (
              <div className="space-y-3 pt-2">
                <h3 className="text-xs font-mono text-slate-400 uppercase tracking-wider">
                  Top Matched Passages ({searchResults.length})
                </h3>
                {searchResults.length === 0 ? (
                  <p className="text-xs font-mono text-slate-500">No matching passages found above similarity threshold.</p>
                ) : (
                  <div className="space-y-2">
                    {searchResults.map((chunk, idx) => (
                      <div
                        key={idx}
                        className="p-3.5 rounded-lg border border-slate-800 bg-sre-950/80 text-xs font-mono space-y-1"
                      >
                        <div className="flex items-center justify-between text-purple-300">
                          <span className="font-semibold">{chunk.document_title}</span>
                          <span className="text-[11px] px-2 py-0.5 rounded bg-purple-950/80 border border-purple-800/60 text-purple-300">
                            Similarity: {(chunk.similarity_score * 100).toFixed(1)}%
                          </span>
                        </div>
                        <p className="text-slate-300 font-sans text-xs pt-1 line-clamp-3">
                          {chunk.content}
                        </p>
                        <div className="text-[10px] text-slate-500 pt-1">
                          Source: {chunk.source} | Chunk: {chunk.chunk_id}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* List of Indexed Documents */}
          <div className="rounded-xl border border-slate-800 bg-sre-900/60 p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h2 className="text-sm font-semibold font-mono text-white flex items-center">
                <FileCode className="w-4 h-4 mr-2 text-cyan-400" />
                Indexed Runbooks ({runbooks.length})
              </h2>
            </div>

            {isLoading ? (
              <LoadingSpinner message="Loading runbooks..." />
            ) : runbooks.length === 0 ? (
              <p className="text-xs font-mono text-slate-500 py-6 text-center">
                No runbooks indexed yet. Upload a Markdown SOP to enable RAG diagnostic citation.
              </p>
            ) : (
              <div className="space-y-2.5">
                {runbooks.map((doc) => (
                  <div
                    key={doc.id}
                    className="p-4 rounded-lg border border-slate-800 bg-sre-950/60 hover:border-slate-700 transition-colors flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 text-xs font-mono"
                  >
                    <div className="space-y-1">
                      <h4 className="font-semibold text-slate-200 text-sm">{doc.title}</h4>
                      <div className="flex items-center space-x-3 text-slate-400 text-[11px]">
                        <span>Source: {doc.source}</span>
                        {doc.service_name && (
                          <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">
                            svc:{doc.service_name}
                          </span>
                        )}
                        <span>Hash: {doc.content_hash.substring(0, 10)}...</span>
                      </div>
                    </div>
                    <div className="flex items-center space-x-2 text-slate-400 flex-shrink-0">
                      <span className="inline-flex items-center px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300 text-xs">
                        <Layers className="w-3 h-3 mr-1 text-slate-400" />
                        {doc.chunk_count} chunks
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
