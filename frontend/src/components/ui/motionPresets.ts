export const fadeIn = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  transition: { duration: 0.2 },
};

export const fadeInScale = {
  initial: { opacity: 0, scale: 0.95 },
  animate: { opacity: 1, scale: 1 },
  transition: { duration: 0.25 },
};

export const slideUp = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.25 },
};

export const slideDown = {
  initial: { opacity: 0, y: -12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.25 },
};

export const slideLeft = {
  initial: { opacity: 0, x: 12 },
  animate: { opacity: 1, x: 0 },
  transition: { duration: 0.25 },
};

export const slideRight = {
  initial: { opacity: 0, x: -12 },
  animate: { opacity: 1, x: 0 },
  transition: { duration: 0.25 },
};

export const staggerChildren = {
  animate: {
    transition: {
      staggerChildren: 0.05,
    },
  },
};
