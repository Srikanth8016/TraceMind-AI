import { describe, it, expect } from 'vitest';
import { getErrorMessage } from '../api/client';
import axios, { AxiosError, AxiosHeaders } from 'axios';

describe('API Client Error Utilities', () => {
  it('extracts string detail from FastAPI HTTPException response', () => {
    const error = new AxiosError(
      'Request failed with status code 404',
      'ERR_BAD_REQUEST',
      undefined,
      undefined,
      {
        status: 404,
        statusText: 'Not Found',
        headers: {},
        config: { headers: new AxiosHeaders() },
        data: { detail: 'Incident with id=123 not found.' },
      }
    );

    const message = getErrorMessage(error);
    expect(message).toBe('Incident with id=123 not found.');
  });

  it('extracts array of field validation errors from FastAPI 422 response', () => {
    const error = new AxiosError(
      'Request failed with status code 422',
      'ERR_BAD_REQUEST',
      undefined,
      undefined,
      {
        status: 422,
        statusText: 'Unprocessable Entity',
        headers: {},
        config: { headers: new AxiosHeaders() },
        data: {
          detail: [
            { msg: 'Field required', loc: ['body', 'title'] },
            { msg: 'Invalid severity enum', loc: ['body', 'severity'] },
          ],
        },
      }
    );

    const message = getErrorMessage(error);
    expect(message).toContain('Field required');
    expect(message).toContain('Invalid severity enum');
  });

  it('falls back to standard Error message if not an AxiosError', () => {
    const err = new Error('Local network timeout');
    expect(getErrorMessage(err)).toBe('Local network timeout');
  });
});
