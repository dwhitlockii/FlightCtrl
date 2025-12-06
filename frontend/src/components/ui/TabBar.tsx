import React from 'react';

type TabBarProps = React.HTMLAttributes<HTMLDivElement>;
type TabItemProps = {
  active?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
};

const TabBarRoot: React.FC<TabBarProps> = ({ className = '', children, ...rest }) => (
  <div className={`ui-tabbar ${className}`} {...rest}>
    {children}
  </div>
);

const TabBarItem: React.FC<TabItemProps> = ({ active, onClick, children }) => (
  <button
    className={`ui-tab-item ${active ? 'active' : ''}`}
    onClick={onClick}
    type="button"
  >
    {children}
  </button>
);

export const TabBar = Object.assign(TabBarRoot, { Item: TabBarItem });
