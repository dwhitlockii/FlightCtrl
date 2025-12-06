import { render, screen } from '@testing-library/react'
import App from './App'

describe('App', () => {
  it('renders header', () => {
    render(<App />)
    expect(screen.getByText(/FlightCtrl AI Agent System/i)).toBeInTheDocument()
  })
})
